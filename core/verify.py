"""Post-save verification: re-read the written file the way an outside tool would.

Seven checks, run after every save:
  1. the file opens and decodes as the expected format,
  2. its pixel size is unchanged,
  3. the container holds exactly one Exif block and no XMP / ICC / IPTC / comment data,
  4. the EXIF holds exactly the intended fields (with the right values) and nothing else,
  5. there is no GPS, thumbnail or other EXIF block,
  6. DateTime equals DateTimeOriginal and matches the intended timestamp,
  7. none of the original file's metadata values appear in the output.

The report also carries one informational note about what still differs from a
genuine iPhone capture. This tool edits metadata; it does not turn a file into a
camera original, and the report says so instead of pretending otherwise.

Command line:  python -m core.verify <image>   (prints the file's structure)
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import piexif
from PIL import Image

from .iphone_models import IPHONE_MODELS, MAKE

# EXIF tags the tool writes (the Exif-IFD pointer tag 0x8769 is structural and ignored)
_TAG_MAKE, _TAG_MODEL, _TAG_SOFTWARE, _TAG_DATETIME, _TAG_DT_ORIGINAL = 271, 272, 305, 306, 36867
_TAG_ORIENTATION = 274
_EXIF_IFD_POINTER = 0x8769
_INFO_NOTE = ("Exposure, lens, MakerNote, GPS, ICC colour profile and thumbnail data that "
              "real iPhone photos carry are not written.")


@dataclass
class Expected:
    """What the saved file should contain."""

    fmt: str                       # Pillow format: "JPEG" or "HEIF"
    size: tuple[int, int]
    model: str | None
    timestamp: datetime
    leak_tokens: tuple[bytes, ...] = ()  # metadata values of the SOURCE file
    orientation: int = 1                 # != 1 only for a lossless JPEG copy of a rotated photo


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class VerifyReport:
    checks: list[Check] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)  # informational, shown only in the details

    def add(self, name: str, ok, detail: str = "") -> None:
        self.checks.append(Check(name, bool(ok), detail))

    @property
    def errors(self) -> list[Check]:
        return [c for c in self.checks if not c.ok]

    @property
    def passed(self) -> bool:
        return not self.errors

    def summary(self) -> str:
        return f"{sum(c.ok for c in self.checks)}/{len(self.checks)} checks passed"

    def text(self) -> str:
        lines = [f"Verification: {self.summary()}", ""]
        for c in self.checks:
            lines.append(f"{'✔' if c.ok else '✘'} {c.name}" + (f" - {c.detail}" if c.detail else ""))
        if self.notes:
            lines += ["", "ℹ Still different from a genuine iPhone capture (not changed by this tool):"]
            lines += [f"  • {n}" for n in self.notes]
        return "\n".join(lines)


# -- container parsers -----------------------------------------------------------
def jpeg_segments(data: bytes) -> list[tuple[int, bytes]]:
    """(marker, payload) for every segment up to the start of the image scan."""
    segments: list[tuple[int, bytes]] = []
    pos = 2  # after SOI
    while pos + 4 <= len(data) and data[pos] == 0xFF:
        marker = data[pos + 1]
        if marker == 0xFF:  # fill byte
            pos += 1
            continue
        if marker in (0xDA, 0xD9):  # start of scan / end of image
            segments.append((marker, b""))
            break
        length = int.from_bytes(data[pos + 2:pos + 4], "big")
        segments.append((marker, data[pos + 4:pos + 2 + length]))
        pos += 2 + length
    return segments


def _boxes(data: bytes, start: int, end: int):
    """Yield (type, payload_start, payload_end) for ISO-BMFF boxes in data[start:end]."""
    pos = start
    while pos + 8 <= end:
        size = int.from_bytes(data[pos:pos + 4], "big")
        kind = data[pos + 4:pos + 8]
        header = 8
        if size == 1:
            size, header = int.from_bytes(data[pos + 8:pos + 16], "big"), 16
        elif size == 0:
            size = end - pos
        if size < header:
            break
        yield kind, pos + header, min(pos + size, end)
        pos += size


def heif_structure(data: bytes) -> tuple[bytes, list[bytes], bool]:
    """(major brand, item types such as hvc1 / Exif / mime, has an embedded ICC profile)."""
    brand, items, icc = b"", [], False
    for kind, s, e in _boxes(data, 0, len(data)):
        if kind == b"ftyp":
            brand = data[s:s + 4]
        elif kind == b"meta":
            for k2, s2, e2 in _boxes(data, s + 4, e):  # 'meta' is a full box: skip version/flags
                if k2 == b"iinf":
                    count_size = 2 if data[s2] == 0 else 4
                    for k3, s3, e3 in _boxes(data, s2 + 4 + count_size, e2):
                        if k3 == b"infe":
                            version = data[s3]
                            type_at = s3 + 4 + (2 if version == 2 else 4) + 2
                            items.append(data[type_at:type_at + 4])
                elif k2 == b"iprp":
                    for k3, s3, e3 in _boxes(data, s2, e2):
                        if k3 == b"ipco":
                            for k4, s4, e4 in _boxes(data, s3, e3):
                                if k4 == b"colr" and data[s4:s4 + 4] in (b"prof", b"rICC"):
                                    icc = True
    return brand, items, icc


def _tiff_from_raw(raw: bytes | None) -> bytes | None:
    """Locate the TIFF header inside raw EXIF bytes (with or without prefixes)."""
    if not raw:
        return None
    for off in range(0, min(len(raw) - 3, 16)):
        if raw[off:off + 4] in (b"MM\x00*", b"II*\x00"):
            return raw[off:]
    return None


def _ascii(value) -> str:
    return value.decode("ascii", "replace").rstrip("\x00") if isinstance(value, bytes) else str(value)


def _tag_name(ifd: str, tag: int) -> str:
    return piexif.TAGS.get(ifd, {}).get(tag, {}).get("name", f"tag {tag}")


def _names(ifd: str, tags) -> str:
    return ", ".join(sorted(_tag_name(ifd, t) for t in tags)) or "none"


# -- the verification ------------------------------------------------------------
def verify_output(path: str | Path, exp: Expected) -> VerifyReport:
    report = VerifyReport()
    add = report.add
    path = Path(path)
    is_jpeg = exp.fmt == "JPEG"
    label = "JPEG" if is_jpeg else "HEIC"

    try:
        data = path.read_bytes()
    except OSError as exc:
        add("Saved file can be read", False, str(exc))
        return report

    # 1 + 2: opens, decodes, size unchanged
    try:
        with Image.open(path) as im:
            im.load()
            fmt, size, mode, info = im.format, im.size, im.mode, dict(im.info)
    except Exception as exc:
        add(f"Opens and decodes as a valid {label} image", False, str(exc))
        return report
    add(f"Opens and decodes as a valid {label} image", fmt == exp.fmt and mode == "RGB", f"{fmt}, {mode}")
    add("Pixel size is unchanged by the conversion", size == exp.size,
        f"{size[0]}x{size[1]}" + ("" if size == exp.size else f" (expected {exp.size[0]}x{exp.size[1]})"))

    # 3: the container holds one Exif block and nothing else
    if is_jpeg:
        segments = jpeg_segments(data)
        exif_blocks, extras = [], []
        for marker, payload in segments:
            if marker == 0xE1 and payload.startswith(b"Exif\x00\x00"):
                exif_blocks.append(payload)
            elif 0xE0 <= marker <= 0xEF or marker == 0xFE:
                extras.append("COM (comment)" if marker == 0xFE else f"APP{marker - 0xE0}")
        add("Container holds exactly one Exif block and no XMP/ICC/IPTC/comment segments",
            len(exif_blocks) == 1 and not extras,
            f"{len(exif_blocks)} Exif block(s)" + (f", unexpected: {', '.join(extras)}" if extras else ""))
        raw_exif = exif_blocks[0] if exif_blocks else None
    else:
        brand, items, icc = heif_structure(data)
        extras = [t.decode("latin-1") for t in items if t not in (b"hvc1", b"Exif")] + (["ICC profile"] if icc else [])
        add("Container holds exactly one Exif item and no XMP/ICC/IPTC metadata",
            brand in (b"heic", b"heix") and items.count(b"Exif") == 1 and not extras,
            f"{items.count(b'Exif')} Exif item(s)" + (f", unexpected: {', '.join(extras)}" if extras else "")
            + ("" if brand in (b"heic", b"heix") else f", brand {brand!r}"))
        raw_exif = info.get("exif")

    # 4 + 5 + 6: EXIF content, read back with piexif
    tiff = _tiff_from_raw(raw_exif)
    parsed = None
    if tiff:
        try:
            parsed = piexif.load(b"Exif\x00\x00" + tiff)
        except Exception as exc:
            add("EXIF block can be parsed", False, str(exc))
    else:
        add("EXIF block can be parsed", False, "no EXIF data found in the file")
    if parsed is not None:
        zeroth = {k: v for k, v in parsed["0th"].items() if k != _EXIF_IFD_POINTER}
        exif_ifd = dict(parsed["Exif"])
        want_zeroth = {_TAG_DATETIME} | ({_TAG_MAKE, _TAG_MODEL, _TAG_SOFTWARE} if exp.model else set())
        if exp.orientation != 1:  # kept so a rotated photo still displays upright
            want_zeroth.add(_TAG_ORIENTATION)
        want_exif = {_TAG_DT_ORIGINAL}

        problems = []
        if set(zeroth) != want_zeroth or set(exif_ifd) != want_exif:
            problems.append(f"expected {_names('0th', want_zeroth)}, {_names('Exif', want_exif)}")
        if exp.model:  # the values must be right, not just present
            wanted = {_TAG_MAKE: MAKE, _TAG_MODEL: exp.model, _TAG_SOFTWARE: IPHONE_MODELS.get(exp.model, "")}
            problems += [f"{_tag_name('0th', t)} is {_ascii(zeroth.get(t, b''))!r}, expected {v!r}"
                         for t, v in wanted.items() if _ascii(zeroth.get(t, b"")) != v]
        if exp.orientation != 1 and zeroth.get(_TAG_ORIENTATION) != exp.orientation:
            problems.append(f"Orientation is {zeroth.get(_TAG_ORIENTATION)!r}, expected {exp.orientation}")
        add("EXIF holds exactly the intended fields and nothing else", not problems,
            f"found {_names('0th', zeroth)}, {_names('Exif', exif_ifd)}"
            + (" | " + "; ".join(problems) if problems else ""))

        others = [n for n in ("GPS", "Interop", "1st") if parsed[n]] + (["thumbnail"] if parsed["thumbnail"] else [])
        add("No GPS, thumbnail or other EXIF blocks", not others, ", ".join(others) or "none")

        stamp = exp.timestamp.strftime("%Y:%m:%d %H:%M:%S")
        dt, dto = _ascii(zeroth.get(_TAG_DATETIME, b"")), _ascii(exif_ifd.get(_TAG_DT_ORIGINAL, b""))
        add("DateTime equals DateTimeOriginal and matches the intended timestamp",
            dt == dto == stamp, f"{dt!r} / {dto!r}")

    # 7: nothing from the original file survived
    injected = [b"Apple", exp.model.encode() if exp.model else b"",
                IPHONE_MODELS.get(exp.model or "", "").encode(), exp.timestamp.strftime("%Y:%m:%d %H:%M:%S").encode()]
    leaked = [t.decode("utf-8", "replace") for t in exp.leak_tokens
              if t in data and not any(t in inj for inj in injected if inj)]
    add("None of the original file's metadata values appear in the output", not leaked,
        f"{len(exp.leak_tokens)} value(s) searched" if not leaked else "found: " + ", ".join(leaked[:5]))

    report.notes.append(_INFO_NOTE)
    return report


def describe(path: str | Path) -> str:
    """Human-readable structure dump (for comparing any file, e.g. a real photo)."""
    path = Path(path)
    data = path.read_bytes()
    lines = [f"{path.name}: {len(data):,} bytes"]
    if data[:2] == b"\xff\xd8":
        for marker, payload in jpeg_segments(data):
            lines.append(f"  segment 0xFF{marker:02X}  {len(payload):>7} bytes  {payload[:12]!r}")
    else:
        brand, items, icc = heif_structure(data)
        lines.append(f"  brand {brand!r}, items {items}, ICC profile: {icc}")
    with Image.open(path) as im:
        ex = im.getexif()
        flat = {k: v for k, v in ex.items() if k != _EXIF_IFD_POINTER}
        flat.update(ex.get_ifd(_EXIF_IFD_POINTER))
        lines.append(f"  {im.format} {im.size[0]}x{im.size[1]} {im.mode}; EXIF fields: {len(flat)}")
        for tag, value in sorted(flat.items()):
            lines.append(f"    {tag:>6}  {str(value)[:70]}")
    return "\n".join(lines)


if __name__ == "__main__":
    for arg in sys.argv[1:]:
        print(describe(arg))
