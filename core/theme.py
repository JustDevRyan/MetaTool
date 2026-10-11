"""Dark theme for MetaTool: palette, stylesheet, generated icons and window icon.

Everything visual lives here so ui.py only deals with layout and behaviour.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from PyQt6.QtCore import QEvent, QObject, QPointF, Qt
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPalette, QPen, QPixmap
from PyQt6.QtWidgets import QApplication, QDialog, QMainWindow, QWidget

from .settings import icon_path

# Palette -------------------------------------------------------------------
BG = "#121317"        # window
CARD = "#1a1b21"      # cards (slightly lighter than window)
BORDER = "#2a2c34"    # 1 px card / input borders
INPUT = "#101115"     # text inputs and dropdown
ZONE = "#111217"      # drop zone (darker than the card)
ZONE_BORDER = "#2f323b"
ZONE_HOVER_BG = "#171922"
TEXT = "#e6e8ee"
MUTED = "#8e929b"
ACCENT = "#5271ff"
ACCENT_HOVER = "#667fff"
ACCENT_PRESSED = "#4159d9"
HOVER_BORDER = "#637cff"

FONT_FAMILIES = ["SF Pro Text", "SF Pro Display", "Segoe UI Variable Text", "Segoe UI", "Arial"]

# Kept at module level so the generated icon files outlive apply_theme()
_icon_dir: tempfile.TemporaryDirectory | None = None


def _make_icon(path: Path, size: int, points: list[tuple[float, float]],
               color: str, width: float) -> None:
    """Draw a simple polyline icon (tick / chevron) to a transparent PNG."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color), width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    line = QPainterPath(QPointF(*points[0]))
    for pt in points[1:]:
        line.lineTo(QPointF(*pt))
    p.drawPath(line)
    p.end()
    pm.save(str(path))


def _build_icons() -> dict[str, str]:
    """Generate the checkbox tick and combo chevrons; return QSS-safe URLs."""
    global _icon_dir
    _icon_dir = tempfile.TemporaryDirectory(prefix="metatool_")
    d = Path(_icon_dir.name)
    _make_icon(d / "check.png", 18, [(4.5, 9.5), (7.5, 12.5), (13.5, 5.5)], "#ffffff", 2.2)
    _make_icon(d / "chev.png", 12, [(2.5, 4.5), (6, 8), (9.5, 4.5)], "#aeb2bc", 1.8)
    _make_icon(d / "chev_off.png", 12, [(2.5, 4.5), (6, 8), (9.5, 4.5)], "#4a4d57", 1.8)
    _make_icon(d / "up.png", 12, [(2.5, 7.5), (6, 4), (9.5, 7.5)], "#aeb2bc", 1.8)
    _make_icon(d / "up_off.png", 12, [(2.5, 7.5), (6, 4), (9.5, 7.5)], "#4a4d57", 1.8)
    return {n: (d / f"{n}.png").as_posix()
            for n in ("check", "chev", "chev_off", "up", "up_off")}


STYLESHEET = """
QToolTip { background:@CARD@; color:@TEXT@; border:1px solid @BORDER@; padding:4px 6px; }
QMessageBox { background:@CARD@; }
QMessageBox QLabel#qt_msgbox_label { min-width:380px; }
QMessageBox QTextEdit { background:@INPUT@; color:@TEXT@; border:1px solid @BORDER@;
            border-radius:8px; font-family:Consolas, 'DejaVu Sans Mono', monospace; font-size:9pt; }

QLabel { color:@TEXT@; }
QLabel#appTitle { font-size:24pt; font-weight:700; color:#f4f5f8; }
QLabel#appSubtitle { font-size:10pt; color:@MUTED@; }
QLabel#cardTitle { font-size:13pt; font-weight:600; color:#f4f5f8; }
QLabel#fieldLabel { font-size:10pt; color:#d5d8df; }
QLabel#fieldLabel:disabled { color:#5c606b; }
QLabel#muted { font-size:9pt; color:@MUTED@; }

/* Cards */
QFrame#card { background:@CARD@; border:1px solid @BORDER@; border-radius:12px; }

/* Result zone (solid, like the drop zone but not interactive) */
QFrame#resultZone { background:@ZONE@; border:1px solid @BORDER@; border-radius:12px; }

/* Right-click menu */
QMenu { background:@CARD@; color:@TEXT@; border:1px solid @BORDER@; padding:4px; }
QMenu::item { padding:6px 24px; border-radius:4px; }
QMenu::item:selected { background:#2b3350; }
QMenu::item:disabled { color:#5c606b; }

/* Drop zone */
QFrame#dropZone { background:@ZONE@; border:2px dashed @ZONE_BORDER@; border-radius:12px; }
QFrame#dropZone[active="true"] { background:@ZONE_HOVER_BG@; border:2px dashed @HOVER_BORDER@; }
QLabel#dropPlus { font-size:44pt; font-weight:300; color:#3b3f4a; }
QLabel#dropTitle { font-size:13pt; font-weight:700; color:#f4f5f8; }
QLabel#dropSub { font-size:10pt; color:@MUTED@; }

/* Inputs */
QLineEdit { background:@INPUT@; color:@TEXT@; border:1px solid @BORDER@; border-radius:8px;
            padding:9px 12px; font-size:10pt; selection-background-color:@ACCENT@;
            placeholder-text-color:#5f636e; }
QLineEdit:focus { border:1px solid @HOVER_BORDER@; }

QComboBox { background:@INPUT@; color:@TEXT@; border:1px solid @BORDER@; border-radius:8px;
            padding:9px 12px; font-size:10pt; combobox-popup:0; }
QComboBox:hover { border:1px solid #3a3d47; }
QComboBox:disabled { background:#14151a; color:#5c606b; border:1px solid #22242b; }
QComboBox::drop-down { border:none; width:30px; }
QComboBox::down-arrow { image:url("@CHEV@"); width:12px; height:12px; }
QComboBox::down-arrow:disabled { image:url("@CHEV_OFF@"); }
QComboBox QAbstractItemView { background:@CARD@; color:@TEXT@; border:1px solid @BORDER@;
            selection-background-color:#2b3350; selection-color:#ffffff; outline:0; padding:4px; }
QScrollBar:vertical { background:transparent; width:10px; margin:2px; }
QScrollBar::handle:vertical { background:#3a3d47; border-radius:3px; min-height:24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }

QFrame#separator { background:@BORDER@; border:none; min-height:1px; max-height:1px; }

/* Time / date editors (QTimeEdit, QDateEdit) */
QDateTimeEdit { background:@INPUT@; color:@TEXT@; border:1px solid @BORDER@; border-radius:8px;
            padding:9px 12px; font-size:10pt; selection-background-color:@ACCENT@; }
QDateTimeEdit:hover { border:1px solid #3a3d47; }
QDateTimeEdit:focus { border:1px solid @HOVER_BORDER@; }
QDateTimeEdit:disabled { background:#14151a; color:#5c606b; border:1px solid #22242b; }
QDateTimeEdit::up-button { subcontrol-origin:border; subcontrol-position:top right;
            width:22px; height:17px; border:none; background:transparent; margin:3px 3px 0 0; }
QDateTimeEdit::down-button { subcontrol-origin:border; subcontrol-position:bottom right;
            width:22px; height:17px; border:none; background:transparent; margin:0 3px 3px 0; }
QDateTimeEdit::up-button:hover, QDateTimeEdit::down-button:hover { background:#23252d; border-radius:5px; }
QDateTimeEdit::up-arrow { image:url("@UP@"); width:10px; height:10px; }
QDateTimeEdit::down-arrow { image:url("@CHEV@"); width:10px; height:10px; }
QDateTimeEdit::up-arrow:disabled { image:url("@UP_OFF@"); }
QDateTimeEdit::down-arrow:disabled { image:url("@CHEV_OFF@"); }
QDateTimeEdit::drop-down { subcontrol-origin:border; subcontrol-position:center right; width:28px; border:none; }

/* Calendar popup of the date editor */
QCalendarWidget QWidget { background:@CARD@; color:@TEXT@; }
QCalendarWidget QToolButton { background:transparent; color:@TEXT@; border:none; border-radius:6px;
            padding:4px 8px; font-size:10pt; }
QCalendarWidget QToolButton:hover { background:#23252d; }
QCalendarWidget QMenu { background:@CARD@; color:@TEXT@; border:1px solid @BORDER@; }
QCalendarWidget QAbstractItemView:enabled { background:@INPUT@; color:@TEXT@; outline:0;
            selection-background-color:@ACCENT@; selection-color:#ffffff; }
QCalendarWidget QAbstractItemView:disabled { color:#5c606b; }

/* Checkbox */
QCheckBox { color:@TEXT@; font-size:10pt; spacing:10px; }
QCheckBox::indicator { width:18px; height:18px; border:1px solid #3a3d47; border-radius:5px;
                       background:@INPUT@; }
QCheckBox::indicator:hover { border:1px solid @HOVER_BORDER@; }
QCheckBox::indicator:checked { background:@ACCENT@; border:1px solid @ACCENT@; image:url("@CHECK@"); }

/* Buttons: secondary by default (Browse, dialogs), primary for Save */
QPushButton { background:#23252d; color:@TEXT@; border:1px solid #30333c; border-radius:7px;
              padding:8px 16px; font-size:10pt; min-width:60px; }
QPushButton:hover { background:#2b2e37; }
QPushButton:pressed { background:#1d1f26; }
QPushButton#primary { background:@ACCENT@; color:#ffffff; border:none; border-radius:7px;
                      font-size:11pt; font-weight:600; min-height:48px; }
QPushButton#primary:hover { background:@ACCENT_HOVER@; }
QPushButton#primary:pressed { background:@ACCENT_PRESSED@; }
QPushButton#primary:disabled { background:#2e3550; color:#7f86a8; }

/* Status bar */
QStatusBar { background:#0c0d10; color:@MUTED@; border-top:1px solid #1f2127; font-size:9pt; }
QStatusBar::item { border:none; }
"""


def apply_theme(app: QApplication) -> None:
    """Install the dark Fusion palette, font and stylesheet on the application."""
    app.setStyle("Fusion")

    font = QFont()
    font.setFamilies(FONT_FAMILIES)
    font.setPointSize(10)
    app.setFont(font)

    pal = QPalette()
    for role, color in {
        QPalette.ColorRole.Window: BG,
        QPalette.ColorRole.WindowText: TEXT,
        QPalette.ColorRole.Base: INPUT,
        QPalette.ColorRole.AlternateBase: CARD,
        QPalette.ColorRole.Text: TEXT,
        QPalette.ColorRole.Button: "#23252d",
        QPalette.ColorRole.ButtonText: TEXT,
        QPalette.ColorRole.Highlight: ACCENT,
        QPalette.ColorRole.HighlightedText: "#ffffff",
        QPalette.ColorRole.ToolTipBase: CARD,
        QPalette.ColorRole.ToolTipText: TEXT,
        QPalette.ColorRole.PlaceholderText: "#5f636e",
    }.items():
        pal.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText, QPalette.ColorRole.ButtonText):
        pal.setColor(QPalette.ColorGroup.Disabled, role, QColor("#5c606b"))
    app.setPalette(pal)

    icons = _build_icons()
    colors = {
        "BG": BG, "CARD": CARD, "BORDER": BORDER, "INPUT": INPUT, "ZONE": ZONE,
        "ZONE_BORDER": ZONE_BORDER, "ZONE_HOVER_BG": ZONE_HOVER_BG, "TEXT": TEXT,
        "MUTED": MUTED, "ACCENT": ACCENT, "ACCENT_HOVER": ACCENT_HOVER,
        "ACCENT_PRESSED": ACCENT_PRESSED, "HOVER_BORDER": HOVER_BORDER,
        "CHECK": icons["check"], "CHEV": icons["chev"], "CHEV_OFF": icons["chev_off"],
        "UP": icons["up"], "UP_OFF": icons["up_off"],
    }
    qss = STYLESHEET
    for key, value in colors.items():
        qss = qss.replace(f"@{key}@", value)
    app.setStyleSheet(qss)

    # App-wide window icon (icon.ico next to the app); missing file -> default icon
    icon = QIcon(str(icon_path())) if icon_path().is_file() else QIcon()
    if not icon.isNull():
        app.setWindowIcon(icon)
    global _chrome_filter
    _chrome_filter = _WindowChromeFilter(app, icon)
    app.installEventFilter(_chrome_filter)


def _colorref(hex_color: str) -> int:
    """'#rrggbb' -> Windows COLORREF (0x00BBGGRR)."""
    c = QColor(hex_color)
    return c.red() | (c.green() << 8) | (c.blue() << 16)


def enable_dark_titlebar(window: QWidget) -> None:
    """Dark title bar on Windows 10 1903+/11, tinted to match the app on Win 11.

    No-op on other platforms; purely cosmetic so failures are ignored.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes
        dwm = ctypes.windll.dwmapi
        hwnd = ctypes.c_void_p(int(window.winId()))

        def set_attr(attr: int, value: int) -> int:
            val = ctypes.c_int(value)
            return dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(val), ctypes.sizeof(val))

        for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (new / old id)
            if set_attr(attr, 1) == 0:
                break
        set_attr(35, _colorref(BG))      # DWMWA_CAPTION_COLOR (Win 11 only)
        set_attr(36, _colorref(TEXT))    # DWMWA_TEXT_COLOR
        set_attr(34, _colorref(BORDER))  # DWMWA_BORDER_COLOR
    except Exception:
        pass


class _WindowChromeFilter(QObject):
    """Gives every window and dialog (message boxes too) the app icon and a dark title bar."""

    def __init__(self, parent: QObject, icon: QIcon) -> None:
        super().__init__(parent)
        self._icon = icon

    def eventFilter(self, obj, event) -> bool:
        if (event.type() == QEvent.Type.Show and isinstance(obj, (QDialog, QMainWindow))
                and obj.isWindow()):
            if not self._icon.isNull():
                obj.setWindowIcon(self._icon)
            enable_dark_titlebar(obj)
        return False


_chrome_filter: _WindowChromeFilter | None = None


def apply_theme(app: QApplication) -> None:
    """Install the dark Fusion palette, font and stylesheet on the application."""
    app.setStyle("Fusion")

    font = QFont()
    font.setFamilies(FONT_FAMILIES)
    font.setPointSize(10)
    app.setFont(font)

    pal = QPalette()
    for role, color in {
        QPalette.ColorRole.Window: BG,
        QPalette.ColorRole.WindowText: TEXT,
        QPalette.ColorRole.Base: INPUT,
        QPalette.ColorRole.AlternateBase: CARD,
        QPalette.ColorRole.Text: TEXT,
        QPalette.ColorRole.Button: "#23252d",
        QPalette.ColorRole.ButtonText: TEXT,
        QPalette.ColorRole.Highlight: ACCENT,
        QPalette.ColorRole.HighlightedText: "#ffffff",
        QPalette.ColorRole.ToolTipBase: CARD,
        QPalette.ColorRole.ToolTipText: TEXT,
        QPalette.ColorRole.PlaceholderText: "#5f636e",
    }.items():
        pal.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText, QPalette.ColorRole.ButtonText):
        pal.setColor(QPalette.ColorGroup.Disabled, role, QColor("#5c606b"))
    app.setPalette(pal)

    icons = _build_icons()
    colors = {
        "BG": BG, "CARD": CARD, "BORDER": BORDER, "INPUT": INPUT, "ZONE": ZONE,
        "ZONE_BORDER": ZONE_BORDER, "ZONE_HOVER_BG": ZONE_HOVER_BG, "TEXT": TEXT,
        "MUTED": MUTED, "ACCENT": ACCENT, "ACCENT_HOVER": ACCENT_HOVER,
        "ACCENT_PRESSED": ACCENT_PRESSED, "HOVER_BORDER": HOVER_BORDER,
        "CHECK": icons["check"], "CHEV": icons["chev"], "CHEV_OFF": icons["chev_off"],
        "UP": icons["up"], "UP_OFF": icons["up_off"],
    }
    qss = STYLESHEET
    for key, value in colors.items():
        qss = qss.replace(f"@{key}@", value)
    app.setStyleSheet(qss)

    # App-wide window icon (icon.ico next to the app); missing file -> default icon
    icon = QIcon(str(icon_path())) if icon_path().is_file() else QIcon()
    if not icon.isNull():
        app.setWindowIcon(icon)
    global _chrome_filter
    _chrome_filter = _WindowChromeFilter(app, icon)
    app.installEventFilter(_chrome_filter)


def _colorref(hex_color: str) -> int:
    """'#rrggbb' -> Windows COLORREF (0x00BBGGRR)."""
    c = QColor(hex_color)
    return c.red() | (c.green() << 8) | (c.blue() << 16)


def enable_dark_titlebar(window: QWidget) -> None:
    """Dark title bar on Windows 10 1903+/11, tinted to match the app on Win 11.

    No-op on other platforms; purely cosmetic so failures are ignored.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes
        dwm = ctypes.windll.dwmapi
        hwnd = ctypes.c_void_p(int(window.winId()))

        def set_attr(attr: int, value: int) -> int:
            val = ctypes.c_int(value)
            return dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(val), ctypes.sizeof(val))

        for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (new / old id)
            if set_attr(attr, 1) == 0:
                break
        set_attr(35, _colorref(BG))      # DWMWA_CAPTION_COLOR (Win 11 only)
        set_attr(36, _colorref(TEXT))    # DWMWA_TEXT_COLOR
        set_attr(34, _colorref(BORDER))  # DWMWA_BORDER_COLOR
    except Exception:
        pass


class _DarkTitleBarFilter(QObject):
    """Applies the dark title bar to every window and dialog (message boxes etc.)."""

    def eventFilter(self, obj, event) -> bool:
        if (event.type() == QEvent.Type.Show and isinstance(obj, (QDialog, QMainWindow))
                and obj.isWindow()):
            enable_dark_titlebar(obj)
        return False


_title_filter: _DarkTitleBarFilter | None = None
