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
from PIL import Image, ImageOps

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

# JPEG chroma subsampling: 0 = 4:4:4 (colours exactly as decoded), 2 = 4:2:0 (what iPhones
# write). 4:2:0 averages the colour channels over 2x2 pixels, which visibly changes sharp
# colour edges, so it is left off. Measured on a photo: 99th-percentile colour error
# (CIE dE) rises from 5 to 11 and the worst pixel from 13 to 40.
JPEG_SUBSAMPLING = 0

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
def convert_to_rgb(src: Source) -> Image.Image:
    """Decode the source (any supported format) into plain 8-bit RGB pixels.

    This is the format-conversion step. Everything JPG and HEIC cannot hold is
    resolved here: transparency is flattened onto white, palette / grayscale /
    16-bit modes become RGB, and the EXIF rotation is baked into the pixels so
    the picture stays upright once the Orientation tag is gone.
    """
    with _open(src) as image:
        img = ImageOps.exif_transpose(image)
        if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
            rgba = img.convert("RGBA")
            flat = Image.new("RGB", rgba.size, (255, 255, 255))
            flat.paste(rgba, mask=rgba.getchannel("A"))
            return flat
        return img.convert("RGB")


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
def build_exif_bytes(model: str | None, stamp: datetime) -> bytes:
    """EXIF block with only the fields we write.

    Phone (optional):   Make, Model, Software (the iOS version)
    Timestamp (always): DateTime, DateTimeOriginal
    """
    text = stamp.strftime("%Y:%m:%d %H:%M:%S").encode()
    zeroth: dict = {piexif.ImageIFD.DateTime: text}
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
    """Encode once, with the EXIF block riding along."""
    if fmt == "JPEG":
        # no optimize=True: its buffer is 2 bytes/pixel at q95, which grainy images can exceed
        kwargs = {"quality": 100, "subsampling": JPEG_SUBSAMPLING}
    else:  # HEIC: 8-bit 4:2:0 HEVC, like an iPhone
        kwargs = {"quality": 100, "chroma": 420}
    buf = io.BytesIO()
    img.save(buf, format=fmt, exif=exif, **kwargs)
    data = buf.getvalue()
    return strip_jfif(data) if fmt == "JPEG" else data


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


def _process(src: Source, out_dir: Path, output_format: str, iphone_model: str | None,
             stamp: datetime, name: str = "") -> SaveResult:
    """convert -> strip -> inject -> save -> verify, for one already-validated source."""
    if not YEAR_MIN <= stamp.year <= YEAR_MAX:
        raise ProcessingError(f"The year must be between {YEAR_MIN} and {YEAR_MAX}.")
    fmt, ext = OUTPUT_FORMATS[output_format]
    leak_tokens = collect_source_tokens(src)        # remembered for the final check
    try:
        converted = convert_to_rgb(src)             # 1. convert
    except Exception as exc:
        raise ProcessingError(f"Failed to read the image:\n{exc}") from exc
    clean = strip_metadata(converted)               # 2. strip everything
    try:
        data = encode_image(clean, fmt, build_exif_bytes(iphone_model, stamp))  # 3. inject
        target = write_with_ios_name(data, out_dir, ext)                        # 4. save
    except ProcessingError:
        raise
    except Exception as exc:
        raise ProcessingError(f"Failed to save the image:\n{exc}") from exc

    try:  # 5. re-read the saved file and check it
        report = verify_output(target, Expected(fmt, clean.size, iphone_model, stamp, leak_tokens))
    except Exception as exc:  # a bug in the check must never lose the saved image
        report = VerifyReport()
        report.add("Verification could run", False, str(exc))
    return SaveResult(target, bool(iphone_model), stamp, report, name)


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
