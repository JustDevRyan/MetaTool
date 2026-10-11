"""cx_Freeze build script for MetaTool: a deliberately lean build.

    pip install cx_Freeze
    python core/setup.py build

Result: build/MetaTool/MetaTool.exe  (distribute the whole MetaTool folder).

Only what the app really uses is bundled:
  * PyQt6: QtCore / QtGui / QtWidgets, the Windows platform plugin, and the ICO
    image plugin (needed to load icon.ico). Every other Qt file is pruned.
  * Pillow: only the BMP / GIF / JPEG / MPO / PNG / TIFF / WebP code. Fonts,
    drawing, colour management, AVIF and every other format plugin are removed.
  * pillow-heif (HEIC read/write), piexif, and the few standard-library modules
    those need.
"""

from __future__ import annotations

import os
import pkgutil
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent  # core/
ROOT = HERE.parent                      # project root: main.py, icon.ico, settings.json
os.chdir(ROOT)                          # build/ and relative paths are anchored at the root
# Make `import core...` resolvable and keep core/ itself off the path
sys.path[:] = [str(ROOT)] + [p for p in sys.path if Path(p or ".").resolve() != HERE]

from cx_Freeze import Executable, setup  # noqa: E402

APP_NAME = "MetaTool"
VERSION = "1.0.0"
MAIN = ROOT / "main.py"
ICON = ROOT / "icon.ico"
BUILD_DIR = ROOT / "build" / APP_NAME
PRUNE = True  # set False to keep every file cx_Freeze copies (e.g. when debugging)

# --------------------------------------------------------------------------
# Pillow: cx_Freeze's hook pulls in the *whole* package. Python modules can be
# excluded by name; the compiled extensions are removed after the build.
# --------------------------------------------------------------------------
PIL_PLUGINS_USED = {  # the only image formats the app reads / writes
    "BmpImagePlugin", "GifImagePlugin", "JpegImagePlugin", "MpoImagePlugin",  # MPO: iPhone JPEGs
    "PngImagePlugin", "TiffImagePlugin", "WebPImagePlugin",  # HEIC comes from pillow-heif
}
PIL_UNUSED_HELPERS = {  # drawing, fonts, colour management, display, filters...
    "ImageFont", "ImageDraw", "ImageDraw2", "ImageCms", "ImageTk", "ImageQt",
    "ImageShow", "ImageGrab", "ImageWin", "ImageMorph", "ImageFilter",
    "ImageStat", "ImageTransform", "ImageEnhance", "ImageContainer", "ImagePath",
    "PSDraw", "PyAccess", "FontFile", "BdfFontFile", "PcfFontFile", "PcdFontFile",
    "GdImageFile", "ContainerIO", "TarIO", "WalImageFile", "_tkinter_finder",
}
# Compiled extensions that only the modules above (or AVIF) use
PIL_UNUSED_BINARIES = (
    "_imagingft", "_imagingcms", "_imagingmorph", "_imagingtk", "_avif",
)


def pillow_excludes() -> list[str]:
    import PIL

    excludes = {f"PIL.{name}" for name in PIL_UNUSED_HELPERS}
    for mod in pkgutil.iter_modules(PIL.__path__):
        if mod.name.endswith("ImagePlugin") and mod.name not in PIL_PLUGINS_USED:
            excludes.add(f"PIL.{mod.name}")
    return sorted(excludes)


# --------------------------------------------------------------------------
# Everything else that must not end up in the build
# --------------------------------------------------------------------------
OTHER_EXCLUDES = [
    # packages that may be installed but are never used
    "tkinter", "_tkinter", "numpy", "defusedxml", "olefile", "IPython", "cffi",
    "setuptools", "pkg_resources", "distutils", "pip", "wheel",
    # unused stdlib
    "unittest", "test", "pydoc", "pydoc_data", "doctest", "lib2to3", "idlelib",
    "curses", "sqlite3", "xmlrpc", "http", "email", "html", "xml",
    "ssl", "_ssl", "asyncio", "concurrent", "multiprocessing", "bz2", "lzma",
    "tarfile", "pyexpat",  # (zipfile is needed for ZIP archive input)
    # unused Qt modules (only QtCore / QtGui / QtWidgets are used)
    "PyQt6.QtNetwork", "PyQt6.QtOpenGL", "PyQt6.QtOpenGLWidgets", "PyQt6.QtSvg",
    "PyQt6.QtSvgWidgets", "PyQt6.QtPrintSupport", "PyQt6.QtDBus", "PyQt6.QtQml",
    "PyQt6.QtQuick", "PyQt6.QtSql", "PyQt6.QtTest", "PyQt6.QtXml",
    "PyQt6.QtMultimedia", "PyQt6.QtWebEngineCore", "PyQt6.QtBluetooth",
]
if sys.version_info >= (3, 12):
    # `random` only falls back to hashlib on Python < 3.12 (3.12+ has a built-in
    # SHA-2). Skipping hashlib avoids bundling OpenSSL's libcrypto (~5 MB).
    OTHER_EXCLUDES += ["hashlib", "_hashlib", "hmac"]

# --------------------------------------------------------------------------
# Post-build pruning of files cx_Freeze copies wholesale
# --------------------------------------------------------------------------
# Windows names. plugin sub-folder -> plugin base names to keep
QT_PLUGINS_KEPT = {
    "platforms": {"qwindows"},   # the Windows window system
    "imageformats": {"qico"},    # reads icon.ico (PNG/BMP are built into QtGui)
}
QT_LIBS_KEPT = {"Qt6Core", "Qt6Gui", "Qt6Widgets"}  # every other Qt6*.dll is removed
OTHER_FILES_REMOVED = ("opengl32sw.dll", "d3dcompiler_47.dll")  # software GL / shader compiler

def _base(filename: str) -> str:
    """'libQt6Core.so.6' / 'Qt6Core.dll' / '_imagingft.cp312-win_amd64.pyd' -> base name."""
    return filename.split(".")[0].removeprefix("lib")


def _remove(path: Path) -> int:
    """Delete a file or folder; return the bytes freed."""
    size = (sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
            if path.is_dir() else path.stat().st_size)
    shutil.rmtree(path) if path.is_dir() else path.unlink()
    return size


def prune_pil(build_dir: Path) -> int:
    """Remove the compiled Pillow extensions the app never imports."""
    freed = 0
    for pil_dir in build_dir.rglob("PIL"):
        if pil_dir.is_dir():
            for f in list(pil_dir.iterdir()):
                if f.is_file() and _base(f.name) in PIL_UNUSED_BINARIES:
                    freed += _remove(f)
    return freed


def prune_qt(build_dir: Path, plugins_kept=None, libs_kept=None, other_removed=None) -> int:
    """Remove unused Qt plugins, translations and libraries."""
    plugins_kept = QT_PLUGINS_KEPT if plugins_kept is None else plugins_kept
    libs_kept = QT_LIBS_KEPT if libs_kept is None else libs_kept
    other_removed = OTHER_FILES_REMOVED if other_removed is None else other_removed
    freed = 0
    for plugins in list(build_dir.rglob("plugins")):
        if not (plugins.is_dir() and plugins.parent.name == "Qt6"):
            continue
        for sub in list(plugins.iterdir()):
            keep = plugins_kept.get(sub.name)
            if keep is None:
                freed += _remove(sub)
                continue
            for plugin in list(sub.iterdir()):
                if _base(plugin.name) not in keep:
                    freed += _remove(plugin)
        for translations in list(plugins.parent.glob("translations")):
            freed += _remove(translations)
    for f in list(build_dir.rglob("*")):
        if not f.is_file():
            continue
        base = _base(f.name)
        if (base.startswith("Qt6") and base not in libs_kept) or f.name.lower() in other_removed:
            freed += _remove(f)
    return freed


def prune_build(build_dir: Path) -> None:
    if not (PRUNE and build_dir.is_dir()):
        return
    freed = prune_pil(build_dir)
    if sys.platform == "win32":  # the Qt file names above are the Windows ones
        freed += prune_qt(build_dir)
    print(f"Pruned unused files: {freed / 1_048_576:.1f} MB freed")


# --------------------------------------------------------------------------
def main() -> None:
    if len(sys.argv) == 1:  # allow a plain `python core/setup.py`
        sys.argv.append("build")

    if not ICON.is_file():
        print(f"WARNING: {ICON} not found - building without an application icon.")

    setup(
        name=APP_NAME,
        version=VERSION,
        description="Strip image metadata and optionally inject phone EXIF",
        options={
            "build_exe": {
                "build_exe": str(BUILD_DIR),
                "path": sys.path,
                "excludes": OTHER_EXCLUDES + pillow_excludes(),
                "include_files": [(str(ICON), "icon.ico")] if ICON.is_file() else [],
                "include_msvcr": True,  # tiny VC++ runtime so it runs on clean Windows installs
                "optimize": 2,          # strip docstrings and asserts from bytecode
            }
        },
        executables=[
            Executable(
                script=str(MAIN),
                base="gui" if sys.platform == "win32" else None,  # no console window
                target_name=APP_NAME,
                icon=str(ICON) if ICON.is_file() else None,       # the .exe's own icon
            )
        ],
    )

    if any(cmd in sys.argv for cmd in ("build", "build_exe")):
        prune_build(BUILD_DIR)


if __name__ == "__main__":
    main()
