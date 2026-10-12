"""Image processing pipeline: convert -> strip -> inject -> save as IMG_XXXX -> verify.

Works on single images and on ZIP archives of photos. Pure Python, no Qt imports,
so it can be tested or reused on its own.
"""

from __future__ import annotations

import io
import random
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Callable

import piexif
from PIL import Image, ImageChops, ImageOps

from .iphone_models import IPHONE_MODELS, MAKE
from .verify import Expected, VerifyReport, verify_output

try:  # HEIC needs the optional pillow-heif package (and its native libheif)
    import pillow_heif

    pillow_heif.register_heif_opener()  # lets Pillow open *and* save HEIC/HEIF
    HEIC_AVAILABLE = True
except Exception:  # missing package or missing native library
    HEIC_AVAILABLE = False

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp", ".gif"}
if HEIC_AVAILABLE:
    SUPPORTED_EXTENSIONS |= {".heic", ".heif"}
ZIP_EXTENSION = ".zip"

# Dropdown label -> (Pillow format name, file extension)
OUTPUT_FORMATS = {"JPG": ("JPEG", ".jpg"), "HEIC": ("HEIF", ".heic")}

# NO image-quality compromise is made unless a format makes it unavoidable:
#   * JPEG source -> JPG: the compressed image data is copied untouched, only the metadata is
#     replaced (lossless: the decoded pixels are identical, nothing is re-encoded).
#   * anything -> HEIC: lossless HEVC (4:4:4 chroma, identity colour matrix), bit-exact.
#   * any other source -> JPG: JPEG cannot store arbitrary pixels exactly, so this uses the
#     highest setting (quality 100, no chroma subsampling). The error is measured and reported.
JPEG_QUALITY = 100
JPEG_SUBSAMPLING = 0  # 4:4:4
HEIC_LOSSLESS = {  # RGB stored directly (identity matrix, full range): bit-exact round trip
    "quality": -1,
    "chroma": 444,
    "nclx_profile": {"color_primaries": 1, "transfer_characteristics": 13,
                     "matrix_coefficients": 0, "full_range_flag": 1},
}

# Allowed range for the user-chosen timestamp
YEAR_MIN, YEAR_MAX = 2000, 2100

# ZIP safety limits
MAX_ZIP_IMAGES = 2000
MAX_MEMBER_BYTES = 300 * 1024 * 1024
MAX_ZIP_BYTES = 3 * 1024 ** 3

Source = Path | bytes  # a file on disk, or the raw bytes of a ZIP member


class ProcessingError(Exception):
    """Raised for any user-facing failure (bad file, unwritable folder...)."""


@dataclass
class SaveResult:
    path: Path
    phone_injected: bool = False
    timestamp: datetime | None = None  # the exact timestamp written
    report: VerifyReport | None = None  # result of the post-save verification
    source_name: str = ""
    max_error: int = 0  # largest per-channel pixel difference introduced by encoding (0 = identical)
    lossless_copy: bool = False  # JPEG data copied without re-encoding
    pixel_notes: list[str] = field(default_factory=list)  # unavoidable changes (transparency, 16-bit...)
    icc_removed: bool = False  # the source had a colour profile, which is stripped


@dataclass
class BatchResult:
    """Outcome of processing a ZIP archive."""

    folder: Path
    results: list[SaveResult] = field(default_factory=list)
    failures: list[tuple[str, str]] = field(default_factory=list)  # (file in zip, reason)
    skipped: int = 0  # entries that are not images (folders, __MACOSX, text files...)

    @property
    def verified(self) -> int:
        return sum(1 for r in self.results if r.report is not None and r.report.passed)


def _open(src: Source) -> Image.Image:
    return Image.open(io.BytesIO(src) if isinstance(src, bytes) else src)


def _verify_image(src: Source) -> None:
    try:
        with _open(src) as im:
            im.verify()
    except Exception as exc:  # corrupt / not really an image
        raise ProcessingError(f"This file is not a valid image:\n{exc}") from exc


def validate_image(path: str | Path) -> Path:
    """Check that ``path`` is a readable, supported image; return it as a Path."""
    p = Path(path)
    if not p.is_file():
        raise ProcessingError(f"File not found:\n{p}")
    if p.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise ProcessingError(
            f"Unsupported file type '{p.suffix}'.\n"
            f"Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))} and {ZIP_EXTENSION}"
        )
    _verify_image(p)
    return p


def custom_timestamp(day: date, hour: int, minute: int) -> datetime:
    """The user's date and HH:mm; the seconds are random, like a real capture."""
    return datetime(day.year, day.month, day.day, hour, minute, random.randint(0, 59))


def batch_timestamps(base: datetime | None, count: int) -> list[datetime]:
    """One timestamp per photo of a ZIP: 1 minute apart, with random seconds.

    custom (``base`` given): the first photo is at ``base``, each next one a minute later.
    today  (``base`` None):  the last photo is "now", earlier ones a minute apart, so no
                             photo ends up with a timestamp in the future.
    """
    def random_seconds(dt: datetime) -> datetime:
        return dt.replace(second=random.randint(0, 59), microsecond=0)

    if base is not None:
        base = base.replace(microsecond=0)
        return [base] + [random_seconds(base + timedelta(minutes=k)) for k in range(1, count)]
    now = datetime.now().replace(microsecond=0)
    return [random_seconds(now - timedelta(minutes=count - 1 - k)) for k in range(count - 1)] + [now]


def collect_source_tokens(src: Source) -> tuple[bytes, ...]:
    """Metadata values of the SOURCE file; the final check makes sure none survive."""
    tokens: set[str] = set()
    try:
        with _open(src) as im:
            exif = im.getexif()
            values = list(exif.values())
            for ifd in (0x8769, 0x8825, 0xA005):  # Exif, GPS, Interop
                try:
                    values += list(exif.get_ifd(ifd).values())
                except Exception:
                    pass
            values += [v for k, v in im.info.items() if k not in ("exif", "icc_profile", "xmp")]
            for key in ("comment", "icc_profile", "xmp"):
                raw = im.info.get(key)
                if isinstance(raw, bytes) and len(raw) >= 16:
                    values.append(raw[:48].decode("latin-1"))
    except Exception:
        return ()
    for v in values:
        if isinstance(v, bytes):
            v = v.decode("latin-1", "ignore")
        if isinstance(v, str) and len(v.strip("\x00 ")) >= 5:
            tokens.add(v.strip("\x00 "))
    return tuple(sorted(t.encode("utf-8", "ignore") for t in tokens))


# -- Step 1: convert -----------------------------------------------------------
def convert_to_rgb(src: Source) -> tuple[Image.Image, list[str]]:
    """Decode the source (any supported format) into plain 8-bit RGB pixels.

    Returns (image, notes). Notes list the rare cases where pixel values must change
    because JPG / HEIC cannot hold them: transparency, 16-bit data, CMYK and the like.
    The EXIF rotation is baked into the pixels so the picture stays upright once the
    Orientation tag is gone.
    """
    notes: list[str] = []
    with _open(src) as image:
        img = ImageOps.exif_transpose(image)
        mode = img.mode
        if mode in ("RGBA", "LA", "PA") or (mode == "P" and "transparency" in img.info):
            rgba = img.convert("RGBA")
            if rgba.getchannel("A").getextrema()[0] < 255:
                notes.append("transparency was flattened onto white (JPG/HEIC cannot keep it)")
            flat = Image.new("RGB", rgba.size, (255, 255, 255))
            flat.paste(rgba, mask=rgba.getchannel("A"))
            return flat, notes
        if mode.startswith("I") or mode == "F":  # 16 / 32-bit grayscale
            notes.append("16/32-bit data was scaled down to 8-bit")
            img = img.point(lambda i: i * (1 / 256)).convert("L") if mode.startswith("I;16") else img.convert("L")
        elif mode not in ("RGB", "L", "P", "1", "RGBX"):
            notes.append(f"{mode} colours were converted to RGB")
        return img.convert("RGB"), notes


# -- Step 2: strip -------------------------------------------------------------
def strip_metadata(img: Image.Image) -> Image.Image:
    """Copy only the pixels onto a brand-new canvas.

    The new image never sees the original's EXIF, XMP, IPTC, ICC profile,
    comments or text chunks, so nothing can leak through.
    """
    clean = Image.new("RGB", img.size)
    clean.frombytes(img.tobytes())  # raw pixel bytes: fast, low memory
    return clean


# -- Step 3: inject ------------------------------------------------------------
def build_exif_bytes(model: str | None, stamp: datetime, orientation: int = 1) -> bytes:
    """EXIF block with only the fields we write.

    Phone (optional):   Make, Model, Software (the iOS version)
    Timestamp (always): DateTime, DateTimeOriginal
    Orientation:        only for a lossless JPEG copy of a rotated photo (pixels are not rotated)
    """
    text = stamp.strftime("%Y:%m:%d %H:%M:%S").encode()
    zeroth: dict = {piexif.ImageIFD.DateTime: text}
    if orientation != 1:
        zeroth[piexif.ImageIFD.Orientation] = orientation
    if model:
        zeroth[piexif.ImageIFD.Make] = MAKE.encode()
        zeroth[piexif.ImageIFD.Model] = model.encode()
        zeroth[piexif.ImageIFD.Software] = IPHONE_MODELS[model].encode()
    exif = {piexif.ExifIFD.DateTimeOriginal: text}
    return piexif.dump({"0th": zeroth, "Exif": exif, "GPS": {}, "1st": {}, "thumbnail": None})


# -- Step 4: encode and save as IMG_XXXX ----------------------------------------
def strip_jfif(data: bytes) -> bytes:
    """Drop the JFIF (APP0) header so a JPEG starts directly with its Exif block, as
    iPhone JPEGs do. Only a header is removed: the decoded pixels are identical."""
    if data[:4] == b"\xff\xd8\xff\xe0" and data[6:11] == b"JFIF\x00":
        length = int.from_bytes(data[4:6], "big")
        return data[:2] + data[4 + length:]
    return data


def encode_image(img: Image.Image, fmt: str, exif: bytes) -> bytes:
    """Encode once at the highest fidelity, with the EXIF block riding along."""
    if fmt == "JPEG":
        # no optimize=True: its buffer is 2 bytes/pixel, which grainy images can exceed
        kwargs = {"quality": JPEG_QUALITY, "subsampling": JPEG_SUBSAMPLING}
    else:
        kwargs = dict(HEIC_LOSSLESS)
    buf = io.BytesIO()
    img.save(buf, format=fmt, exif=exif, **kwargs)
    data = buf.getvalue()
    return strip_jfif(data) if fmt == "JPEG" else data


# -- Lossless JPEG copy: new metadata, same compressed image data ---------------------
_UNSUPPORTED_SOF = {0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}


def rebuild_jpeg(data: bytes, exif: bytes) -> bytes | None:
    """The same JPEG with every APPn / COM segment dropped and ``exif`` as the only metadata.

    Quantisation / Huffman tables and all scan data are copied byte for byte, so nothing is
    re-encoded. Returns None when the file is not a plain 8-bit YCbCr JPEG (grayscale, CMYK,
    RGB-coded, lossless or arithmetic coding): those fall back to a normal encode.
    """
    if data[:2] != b"\xff\xd8" or len(exif) + 2 > 0xFFFF:
        return None
    out = [b"\xff\xd8", b"\xff\xe1" + (len(exif) + 2).to_bytes(2, "big") + exif]
    pos, n = 2, len(data)
    sof = None
    adobe_transform = None
    while pos + 2 <= n:
        if data[pos] != 0xFF:
            return None
        marker = data[pos + 1]
        if marker == 0xFF:  # fill byte
            pos += 1
            continue
        if marker == 0xD9:  # EOI: anything after it (MPF previews, trailers) is dropped
            out.append(b"\xff\xd9")
            break
        if pos + 4 > n:
            return None
        length = int.from_bytes(data[pos + 2:pos + 4], "big")
        end = pos + 2 + length
        if length < 2 or end > n:
            return None
        payload = data[pos + 4:end]
        if 0xE0 <= marker <= 0xEF or marker == 0xFE:  # APPn / COM: dropped
            if marker == 0xEE and payload[:5] == b"Adobe" and len(payload) >= 12:
                adobe_transform = payload[11]
            pos = end
            continue
        if marker in _UNSUPPORTED_SOF or marker == 0xCC:
            return None
        if marker in (0xC0, 0xC1, 0xC2):
            sof = payload
        out.append(data[pos:end])
        pos = end
        if marker == 0xDA:  # SOS: copy the entropy-coded scan up to the next real marker
            j = pos
            while True:
                k = data.find(b"\xff", j)
                if k == -1 or k + 1 >= n:
                    return None
                nxt = data[k + 1]
                if nxt == 0x00 or 0xD0 <= nxt <= 0xD7:  # stuffed byte / restart marker
                    j = k + 2
                elif nxt == 0xFF:
                    j = k + 1
                else:
                    break
            out.append(data[pos:k])
            pos = k
    else:
        return None  # ran off the end without an EOI
    if sof is None or sof[0] != 8 or sof[5] != 3:  # 8-bit, three components only
        return None
    if adobe_transform == 0 or tuple(sof[6:15:3]) == (ord("R"), ord("G"), ord("B")):
        return None  # RGB-coded JPEG: dropping its Adobe marker would change the colours
    return b"".join(out)


def lossless_jpeg_copy(src: Source, model: str | None, stamp: datetime):
    """(new JPEG bytes, stored size, orientation) for a safe, bit-exact copy, else None."""
    raw = src if isinstance(src, bytes) else Path(src).read_bytes()
    if raw[:2] != b"\xff\xd8":
        return None
    try:
        with Image.open(io.BytesIO(raw)) as im:
            size, orientation = im.size, im.getexif().get(0x0112, 1)
        orientation = orientation if orientation in range(1, 9) else 1
        rebuilt = rebuild_jpeg(raw, build_exif_bytes(model, stamp, orientation))
        if rebuilt is None:
            return None
        with Image.open(io.BytesIO(raw)) as a, Image.open(io.BytesIO(rebuilt)) as b:
            a.load()
            b.load()  # safety net: refuse the shortcut unless the decoded pixels are identical
            if (a.size, a.mode) != (b.size, b.mode) or a.tobytes() != b.tobytes():
                return None
        return rebuilt, size, orientation
    except Exception:
        return None


def max_pixel_error(path: Path, reference: Image.Image) -> int:
    """Largest per-channel difference between a saved image and the pixels that were encoded."""
    with Image.open(path) as im:
        out = im.convert("RGB")
        out.load()
    if out.size != reference.size:
        return 255
    return max(hi for _lo, hi in ImageChops.difference(out, reference).getextrema())


_IMG_NAME = re.compile(r"^IMG_(\d{4})\.", re.IGNORECASE)


def _used_numbers(out_dir: Path) -> set[int]:
    """Numbers already taken by IMG_XXXX.* files (any extension) in out_dir."""
    return {int(m.group(1)) for f in out_dir.iterdir() if (m := _IMG_NAME.match(f.name))}


def write_with_ios_name(data: bytes, out_dir: Path, ext: str) -> Path:
    """Write as IMG_0001..IMG_9999 using a random number that is not taken yet.

    A taken number is never overwritten or skipped: a new random number is
    drawn until a free one is found. The file is created in exclusive mode
    ("xb"), so even a name that appears between the check and the save is
    detected and re-rolled.
    """
    used = _used_numbers(out_dir)
    while True:
        if len(used) >= 9999:
            raise ProcessingError("All names IMG_0001 to IMG_9999 are already used in this folder.")
        number = random.randint(1, 9999)
        if number in used:
            continue
        target = out_dir / f"IMG_{number:04d}{ext}"
        try:
            handle = open(target, "xb")  # fails instead of overwriting
        except FileExistsError:
            used.add(number)
            continue
        try:
            with handle:
                handle.write(data)
        except Exception:
            target.unlink(missing_ok=True)  # never leave a half-written file
            raise
        return target


# -- Pipeline ------------------------------------------------------------------
def _check_options(output_format: str, iphone_model: str | None) -> None:
    if output_format not in OUTPUT_FORMATS:
        raise ProcessingError(f"Unknown output format: {output_format}")
    if output_format == "HEIC" and not HEIC_AVAILABLE:
        raise ProcessingError("HEIC support is unavailable (pillow-heif is not installed).")
    if iphone_model is not None and iphone_model not in IPHONE_MODELS:
        raise ProcessingError(f"Unknown phone model: {iphone_model}")


def _make_dir(folder: Path) -> Path:
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ProcessingError(f"Cannot create output folder:\n{exc}") from exc
    return folder


def _has_icc(src: Source) -> bool:
    try:
        with _open(src) as im:
            return bool(im.info.get("icc_profile"))
    except Exception:
        return False


def _process(src: Source, out_dir: Path, output_format: str, iphone_model: str | None,
             stamp: datetime, name: str = "") -> SaveResult:
    """convert -> strip -> inject -> save -> verify, for one already-validated source."""
    if not YEAR_MIN <= stamp.year <= YEAR_MAX:
        raise ProcessingError(f"The year must be between {YEAR_MIN} and {YEAR_MAX}.")
    fmt, ext = OUTPUT_FORMATS[output_format]
    leak_tokens = collect_source_tokens(src)        # remembered for the final check
    icc_removed = _has_icc(src)

    data = None
    clean = None
    notes: list[str] = []
    orientation = 1
    if fmt == "JPEG":  # a JPEG stays untouched: only its metadata is swapped
        copy = lossless_jpeg_copy(src, iphone_model, stamp)
        if copy:
            data, size, orientation = copy
    lossless_copy = data is not None
    if data is None:
        try:
            converted, notes = convert_to_rgb(src)  # 1. convert
        except Exception as exc:
            raise ProcessingError(f"Failed to read the image:\n{exc}") from exc
        clean = strip_metadata(converted)           # 2. strip everything
        size = clean.size
    try:
        if data is None:
            data = encode_image(clean, fmt, build_exif_bytes(iphone_model, stamp))  # 3. inject
        target = write_with_ios_name(data, out_dir, ext)                           # 4. save
    except ProcessingError:
        raise
    except Exception as exc:
        raise ProcessingError(f"Failed to save the image:\n{exc}") from exc

    max_error = 0
    if clean is not None:  # measure what the encoder did to the pixels
        try:
            max_error = max_pixel_error(target, clean)
        except Exception:
            max_error = 255
    try:  # 5. re-read the saved file and check it
        report = verify_output(target, Expected(fmt, size, iphone_model, stamp, leak_tokens, orientation))
    except Exception as exc:  # a bug in the check must never lose the saved image
        report = VerifyReport()
        report.add("Verification could run", False, str(exc))
    return SaveResult(target, bool(iphone_model), stamp, report, name,
                      max_error, lossless_copy, notes, icc_removed)


def process_image(
    source: str | Path,
    out_dir: str | Path,
    output_format: str = "JPG",
    iphone_model: str | None = None,
    timestamp: datetime | None = None,
) -> SaveResult:
    """Process one image file.

    ``iphone_model=None`` skips the phone fields. ``timestamp=None`` writes the
    current date and time; pass a datetime to write a custom one.
    """
    _check_options(output_format, iphone_model)
    source = validate_image(source)
    stamp = (timestamp or datetime.now()).replace(microsecond=0)
    out = _make_dir(Path(out_dir))
    return _process(source, out, output_format, iphone_model, stamp, source.name)


# -- ZIP archives --------------------------------------------------------------
_JUNK_NAMES = {".ds_store", "thumbs.db", "desktop.ini"}
_RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                   *(f"LPT{i}" for i in range(1, 10))}


def safe_folder_name(stem: str) -> str:
    """The ZIP's name made safe to use as a folder name."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", stem).strip(" .")
    if not name:
        name = "photos"
    if name.split(".")[0].upper() in _RESERVED_NAMES:
        name = f"_{name}"
    return name[:120]


def _natural_key(text: str) -> list:
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", text)]


def _open_zip(path: str | Path) -> zipfile.ZipFile:
    try:
        return zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as exc:
        raise ProcessingError(f"This is not a readable ZIP archive:\n{exc}") from exc


def _image_members(zf: zipfile.ZipFile) -> tuple[list[zipfile.ZipInfo], int]:
    """(photos in natural name order, number of ignored non-photo entries)."""
    members, skipped = [], 0
    for info in zf.infolist():
        if info.is_dir():
            continue
        parts = PurePosixPath(info.filename.replace("\\", "/")).parts
        name = parts[-1] if parts else ""
        if ("__MACOSX" in parts or name.startswith("._") or name.lower() in _JUNK_NAMES
                or Path(name).suffix.lower() not in SUPPORTED_EXTENSIONS):
            skipped += 1
            continue
        members.append(info)
    members.sort(key=lambda i: _natural_key(i.filename))
    return members, skipped


def count_zip_images(path: str | Path) -> int:
    """Number of photos inside a ZIP (raises ProcessingError when unusable)."""
    with _open_zip(path) as zf:
        members, _ = _image_members(zf)
    if not members:
        raise ProcessingError("This ZIP archive contains no supported images.")
    return len(members)


def process_zip(
    zip_path: str | Path,
    out_dir: str | Path,
    output_format: str = "JPG",
    iphone_model: str | None = None,
    timestamp: datetime | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> BatchResult:
    """Process every photo of a ZIP into ``out_dir/<zip name>/``.

    Photos are processed in natural name order; their timestamps are one minute
    apart with random seconds (see ``batch_timestamps``).
    """
    _check_options(output_format, iphone_model)
    zip_path = Path(zip_path)
    with _open_zip(zip_path) as zf:
        members, skipped = _image_members(zf)
        if not members:
            raise ProcessingError("This ZIP archive contains no supported images.")
        if len(members) > MAX_ZIP_IMAGES:
            raise ProcessingError(f"The ZIP holds {len(members)} images; the limit is {MAX_ZIP_IMAGES}.")
        if sum(m.file_size for m in members) > MAX_ZIP_BYTES:
            raise ProcessingError("The images in this ZIP are too large to process in one go.")

        folder = _make_dir(Path(out_dir) / safe_folder_name(zip_path.stem))
        batch = BatchResult(folder=folder, skipped=skipped)

        # Pass 1: find the photos that can really be processed, so that corrupt or
        # protected files never take a timestamp slot (no gaps in the sequence).
        usable: list[zipfile.ZipInfo] = []
        for member in members:
            try:
                if member.flag_bits & 0x1:
                    raise ProcessingError("password-protected")
                if member.file_size > MAX_MEMBER_BYTES:
                    raise ProcessingError("file is too large")
                _verify_image(zf.read(member))
                usable.append(member)
            except ProcessingError as exc:
                batch.failures.append((member.filename, str(exc).splitlines()[0].rstrip(":")))
            except Exception as exc:
                batch.failures.append((member.filename, f"unexpected error: {exc}"))

        # Pass 2: process them, one minute apart.
        stamps = batch_timestamps(timestamp, len(usable))
        for index, (member, stamp) in enumerate(zip(usable, stamps), start=1):
            if progress:
                progress(index - 1, len(usable))
            try:
                batch.results.append(_process(zf.read(member), folder, output_format,
                                              iphone_model, stamp, member.filename))
            except ProcessingError as exc:
                batch.failures.append((member.filename, str(exc).splitlines()[0].rstrip(":")))
            except Exception as exc:  # one bad file must not stop the rest
                batch.failures.append((member.filename, f"unexpected error: {exc}"))
        if progress:
            progress(len(usable), len(usable))
    return batch


# -- previews --------------------------------------------------------------------
def make_preview_rgba(path: str | Path, max_side: int = 1200) -> tuple[bytes, int, int]:
    """Small RGBA thumbnail for the UI: (raw bytes, width, height).

    EXIF rotation is applied so the preview matches how the image looks.
    """
    with Image.open(path) as src:
        src.draft("RGB", (max_side, max_side))  # fast JPEG downscale; no-op otherwise
        thumb = ImageOps.exif_transpose(src)
        thumb.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        thumb = thumb.convert("RGBA")
        return thumb.tobytes("raw", "RGBA"), thumb.width, thumb.height


def read_rgb_bytes(path: str | Path) -> tuple[bytes, int, int]:
    """Full-resolution RGB pixels of a saved image (used for copying to the clipboard)."""
    with Image.open(path) as im:
        rgb = im.convert("RGB")
        return rgb.tobytes(), rgb.width, rgb.height
