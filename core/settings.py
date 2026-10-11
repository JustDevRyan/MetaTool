"""Persistent settings (JSON) and app-location helpers."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from pathlib import Path


def app_dir() -> Path:
    """Folder that contains the app (works for scripts and frozen .exe builds)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent  # core/ lives inside the app folder


def icon_path() -> Path:
    return app_dir() / "icon.ico"


def default_output_dir() -> Path:
    return app_dir() / "output"


def settings_path() -> Path:
    """settings.json next to the app; falls back to the home folder if read-only."""
    base = app_dir()
    if os.access(base, os.W_OK):
        return base / "settings.json"
    return Path.home() / ".metatool" / "settings.json"


# Expected JSON types per field, used to ignore corrupt / hand-edited values
_TYPES: dict[str, tuple] = {
    "output_format": (str,),
    "inject_metadata": (bool,),
    "phone_model": (str,),
    "inject_timestamp": (bool,),
    "timestamp_date": (str,),  # ISO "YYYY-MM-DD"
    "timestamp_time": (str,),  # "HH:MM:SS"
    "output_dir": (str, type(None)),
    "window_width": (int,),
    "window_height": (int,),
}


@dataclass
class Settings:
    output_format: str = "JPG"  # "JPG" or "HEIC"
    inject_metadata: bool = False
    phone_model: str = "iPhone 15 Pro"
    inject_timestamp: bool = False
    timestamp_date: str = field(default_factory=lambda: datetime.now().date().isoformat())
    timestamp_time: str = "12:00:00"
    output_dir: str | None = None  # None -> default <app folder>/output
    window_width: int = 1200
    window_height: int = 800

    @classmethod
    def load(cls) -> "Settings":
        """Read settings.json; any problem silently falls back to defaults."""
        settings = cls()
        try:
            data = json.loads(settings_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return settings
        if not isinstance(data, dict):
            return settings
        for f in fields(cls):
            value = data.get(f.name)
            ok = isinstance(value, _TYPES[f.name])
            if isinstance(value, bool) and bool not in _TYPES[f.name]:
                ok = False  # True/False must not pass as an int
            if ok and f.name in data:
                setattr(settings, f.name, value)
        return settings

    def save(self) -> bool:
        """Write atomically; returns False if the file could not be written."""
        path = settings_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
            tmp.replace(path)
            return True
        except OSError:
            return False
