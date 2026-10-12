"""PyQt6 user interface (layout and behaviour) for MetaTool. Styling: theme.py."""

from __future__ import annotations

import tempfile
from datetime import date
from pathlib import Path

from PyQt6.QtCore import QDate, QMimeData, QRectF, QSize, Qt, QThread, QTime, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPainterPath
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QLayout,
    QLineEdit, QMainWindow, QMenu, QMessageBox, QPushButton, QSizePolicy,
    QTimeEdit, QDateEdit, QVBoxLayout, QWidget,
)

from .iphone_models import IPHONE_MODELS
from .processor import (
    OUTPUT_FORMATS, SUPPORTED_EXTENSIONS, YEAR_MAX, YEAR_MIN, ZIP_EXTENSION, BatchResult,
    ProcessingError, SaveResult, count_zip_images, custom_timestamp, make_preview_rgba,
    process_image, process_zip, read_rgb_bytes, validate_image,
)
from .settings import Settings, default_output_dir

FILE_FILTER = ("Images and ZIP archives ("
               + " ".join(f"*{e}" for e in sorted(SUPPORTED_EXTENSIONS | {ZIP_EXTENSION})) + ")")


# -- small layout helpers ----------------------------------------------------
def _make_card(title: str) -> tuple[QFrame, QVBoxLayout]:
    """Rounded card with a title; returns (card, its content layout)."""
    card = QFrame()
    card.setObjectName("card")
    lay = QVBoxLayout(card)
    lay.setContentsMargins(20, 20, 20, 20)
    lay.setSpacing(12)
    heading = QLabel(title)
    heading.setObjectName("cardTitle")
    lay.addWidget(heading)
    return card, lay


def _labeled(label: QLabel | str, content: QWidget | QLayout) -> QVBoxLayout:
    """A field label stacked tightly above its widget/layout."""
    if isinstance(label, str):
        label = QLabel(label)
        label.setObjectName("fieldLabel")
    box = QVBoxLayout()
    box.setSpacing(6)
    box.addWidget(label)
    if isinstance(content, QLayout):
        box.addLayout(content)
    else:
        box.addWidget(content)
    return box


def _separator() -> QFrame:
    line = QFrame()
    line.setObjectName("separator")
    return line


def _muted(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("muted")
    lbl.setWordWrap(True)
    return lbl


def make_zip_icon(size: int = 512) -> QImage:
    """A compressed-folder icon (amber folder with a zipper), drawn in code."""
    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(size / 100, size / 100)  # draw on a 100 x 100 grid
    p.setPen(Qt.PenStyle.NoPen)

    back = QPainterPath()  # folder back with its tab
    back.addRoundedRect(QRectF(8, 20, 84, 62), 6, 6)
    tab = QPainterPath()
    tab.addRoundedRect(QRectF(8, 11, 38, 18), 5, 5)
    p.setBrush(QColor("#d99a2b"))
    p.drawPath(back.united(tab))
    p.setBrush(QColor("#f5c453"))  # folder front
    p.drawRoundedRect(QRectF(8, 30, 84, 54), 6, 6)

    p.setBrush(QColor("#e9ecf2"))  # zipper track running down the middle
    p.drawRect(QRectF(44, 11, 12, 52))
    for i in range(10):  # interlocking teeth
        y = 13 + i * 5
        p.setBrush(QColor("#7d8392"))
        p.drawRect(QRectF(44, y, 6, 2.6))
        p.setBrush(QColor("#b4bac8"))
        p.drawRect(QRectF(50, y + 2.5, 6, 2.6))
    p.setBrush(QColor("#4f5565"))  # slider and pull tab
    p.drawRoundedRect(QRectF(43, 60, 14, 9, ), 2.5, 2.5)
    p.drawRoundedRect(QRectF(45, 68, 10, 14), 3, 3)
    p.setBrush(QColor("#f5c453"))
    p.drawEllipse(QRectF(48.2, 72, 3.6, 3.6))
    p.end()
    return img


class ImagePreview(QWidget):
    """Paints a rounded, aspect-correct preview centred in the space available."""

    def __init__(self) -> None:
        super().__init__()
        self._image = QImage()
        self._scaled = QImage()
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.setMinimumSize(80, 80)

    def set_image(self, image: QImage) -> None:
        self._image = image
        self._rescale()
        self.update()

    def _rescale(self) -> None:
        if self._image.isNull() or self.width() <= 0 or self.height() <= 0:
            self._scaled = QImage()
            return
        dpr = self.devicePixelRatioF()
        self._scaled = self._image.scaled(
            QSize(int(self.width() * dpr), int(self.height() * dpr)),
            Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self._scaled.setDevicePixelRatio(dpr)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._rescale()

    def paintEvent(self, event) -> None:
        if self._scaled.isNull():
            return
        dpr = self._scaled.devicePixelRatio()
        w, h = self._scaled.width() / dpr, self._scaled.height() / dpr
        rect = QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        clip = QPainterPath()
        clip.addRoundedRect(rect, 8, 8)
        painter.setClipPath(clip)
        painter.drawImage(rect.topLeft(), self._scaled)
        painter.end()


class DropZone(QFrame):
    """Large portrait drop target; the whole rectangle is clickable."""

    fileSelected = pyqtSignal(str)
    IDLE_TITLE = "Drop an image or ZIP here"
    IDLE_SUB = "or click to browse"

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("dropZone")
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumSize(300, 380)  # portrait by default
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setProperty("active", False)

        self._full_title = self.IDLE_TITLE
        self._plus = QLabel("＋")
        self._plus.setObjectName("dropPlus")
        self._preview = ImagePreview()
        self._preview.hide()
        self._title = QLabel(self.IDLE_TITLE)
        self._title.setObjectName("dropTitle")
        self._sub = QLabel(self.IDLE_SUB)
        self._sub.setObjectName("dropSub")

        # Layout slots: 0 spacer, 1 plus, 2 preview, 3 title, 4 sub, 5 spacer.
        # Idle: spacers centre the "+" and texts. Loaded: the preview takes the space.
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(16, 16, 16, 16)
        self._lay.setSpacing(8)
        self._lay.addStretch(1)
        self._lay.addWidget(self._plus)
        self._lay.addWidget(self._preview)
        self._lay.addWidget(self._title)
        self._lay.addWidget(self._sub)
        self._lay.addStretch(1)
        for lbl in (self._plus, self._title, self._sub):
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            # Let the frame itself receive hover / click events
            lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    # -- state -------------------------------------------------------------
    def set_loaded(self, filename: str, preview: QImage, subtitle: str) -> None:
        """Show the filename, a status line and (if available) the image / ZIP icon."""
        self._full_title = filename
        self._sub.setText(subtitle)
        self.setToolTip(filename)
        if not preview.isNull():
            self._preview.set_image(preview)
            self._plus.hide()
            self._preview.show()
            for idx, stretch in ((0, 0), (2, 1), (5, 0)):
                self._lay.setStretch(idx, stretch)
        self._elide_title()

    def _elide_title(self) -> None:
        fm = self._title.fontMetrics()
        width = max(self.width() - 48, 80)
        self._title.setText(
            fm.elidedText(self._full_title, Qt.TextElideMode.ElideMiddle, width))

    def _set_active(self, active: bool) -> None:
        """Toggle the hover look (re-polish so the QSS [active] rule applies)."""
        self.setProperty("active", active)
        self.style().unpolish(self)
        self.style().polish(self)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._elide_title()

    # -- hover -------------------------------------------------------------
    def enterEvent(self, event) -> None:
        self._set_active(True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._set_active(False)
        super().leaveEvent(event)

    # -- drag & drop / click -----------------------------------------------
    @staticmethod
    def _first_local_file(mime) -> str | None:
        if mime.hasUrls():
            for url in mime.urls():
                if url.isLocalFile():
                    return url.toLocalFile()
        return None

    def dragEnterEvent(self, event) -> None:
        if self._first_local_file(event.mimeData()):
            event.acceptProposedAction()
            self._set_active(True)
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:
        self._set_active(False)

    def dropEvent(self, event) -> None:
        self._set_active(self.underMouse())
        path = self._first_local_file(event.mimeData())
        if path:
            self.fileSelected.emit(path)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            path, _ = QFileDialog.getOpenFileName(self, "Select an image or ZIP", "", FILE_FILTER)
            self._set_active(self.underMouse())  # leave event is lost while the dialog is open
            if path:
                self.fileSelected.emit(path)


class ResultView(QFrame):
    """Shows the processed image (or a ZIP notice). Right-click -> Copy."""

    message = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("resultZone")
        self.setMinimumSize(280, 380)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._path: Path | None = None

        self._preview = ImagePreview()
        self._title = QLabel()
        self._title.setObjectName("dropTitle")
        self._sub = QLabel()
        self._sub.setObjectName("dropSub")
        self._sub.setWordWrap(True)
        self._full_title = ""
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(8)
        lay.addStretch(1)
        lay.addWidget(self._preview, 1)
        lay.addWidget(self._title)
        lay.addWidget(self._sub)
        lay.addStretch(1)
        self._spacers = (0, 4)
        for lbl in (self._title, self._sub):
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lay = lay
        self.clear()

    def _show(self, image: QImage | None, title: str, subtitle: str) -> None:
        has_image = image is not None and not image.isNull()
        self._preview.setVisible(has_image)
        if has_image:
            self._preview.set_image(image)
        for idx in self._spacers:  # centre the text when there is no picture
            self._lay.setStretch(idx, 0 if has_image else 1)
        self._full_title = title
        self._sub.setText(subtitle)
        self._elide_title()

    def _elide_title(self) -> None:
        fm = self._title.fontMetrics()
        self._title.setText(fm.elidedText(self._full_title, Qt.TextElideMode.ElideMiddle,
                                          max(self.width() - 48, 80)))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._elide_title()

    # -- states ------------------------------------------------------------
    def clear(self) -> None:
        self._path = None
        self.setToolTip("")
        self._show(None, "No result yet", "The processed image appears here after saving")

    def show_image(self, preview: QImage, path: Path, subtitle: str) -> None:
        self._path = path
        self.setToolTip(f"{path}\nRight-click to copy")
        self._show(preview, path.name, subtitle)

    def show_zip(self, icon: QImage, subtitle: str) -> None:
        self._path = None  # nothing to copy for an archive
        self.setToolTip("")
        self._show(icon, "ZIP preview unavailable", subtitle)

    # -- copy ----------------------------------------------------------------
    def build_menu(self) -> QMenu:
        menu = QMenu(self)
        copy = menu.addAction("Copy")
        copy.setEnabled(self._path is not None)
        copy.triggered.connect(self.copy_to_clipboard)
        return menu

    def contextMenuEvent(self, event) -> None:
        self.build_menu().exec(event.globalPos())

    def copy_to_clipboard(self) -> None:
        """Copy the processed image (full resolution) plus the file itself."""
        if self._path is None:
            return
        try:
            data, w, h = read_rgb_bytes(self._path)
            image = QImage(data, w, h, w * 3, QImage.Format.Format_RGB888).copy()
            mime = QMimeData()
            mime.setImageData(image)                                  # paste into editors / chats
            mime.setUrls([QUrl.fromLocalFile(str(self._path))])       # paste into Explorer / attach as file
            QGuiApplication.clipboard().setMimeData(mime)
            self.message.emit(f"Copied {self._path.name} to the clipboard")
        except Exception as exc:
            self.message.emit(f"Could not copy the image: {exc}")


class SaveWorker(QThread):
    """Runs the pipeline off the GUI thread so large images / ZIPs don't freeze the UI."""

    succeeded = pyqtSignal(object)  # SaveResult or BatchResult
    failed = pyqtSignal(str)
    progress = pyqtSignal(int, int)  # (done, total) while a ZIP is processed

    def __init__(self, source, out_dir, output_format, model, timestamp) -> None:
        super().__init__()
        self._args = (source, out_dir, output_format, model, timestamp)

    def run(self) -> None:
        try:
            if Path(self._args[0]).suffix.lower() == ZIP_EXTENSION:
                self.succeeded.emit(process_zip(*self._args, self.progress.emit))
            else:
                self.succeeded.emit(process_image(*self._args))
        except ProcessingError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # last-resort safety net
            self.failed.emit(f"Unexpected error:\n{exc}")


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("MetaTool")
        self._settings = Settings.load()
        self.resize(max(self._settings.window_width, 1180), max(self._settings.window_height, 800))

        self._source: Path | None = None
        # None -> default "<app folder>/output"; set only when the user picks a folder
        self._custom_out_dir: Path | None = (
            Path(self._settings.output_dir) if self._settings.output_dir else None)
        self._worker: SaveWorker | None = None
        self._custom_timestamp = False
        self._zip_icon = make_zip_icon()

        self._build_ui()
        self._restore_settings()
        self.statusBar().setSizeGripEnabled(False)
        self.statusBar().setContentsMargins(10, 0, 0, 0)
        self.statusBar().showMessage("Ready")

    # -- UI construction ---------------------------------------------------
    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(18)

        # Header: app name + muted subtitle on the same baseline
        header = QHBoxLayout()
        header.setSpacing(12)
        title = QLabel("MetaTool")
        title.setObjectName("appTitle")
        subtitle = QLabel("Clean image metadata & optionally inject phone EXIF")
        subtitle.setObjectName("appSubtitle")
        subtitle.setContentsMargins(0, 0, 0, 5)
        header.addWidget(title, 0, Qt.AlignmentFlag.AlignBottom)
        header.addWidget(subtitle, 0, Qt.AlignmentFlag.AlignBottom)
        header.addStretch(1)
        outer.addLayout(header)

        # Three columns: input | metadata + output | result preview
        columns = QHBoxLayout()
        columns.setSpacing(16)
        columns.addWidget(self._build_input_card(), 3)
        columns.addLayout(self._build_right_column(), 2)
        columns.addWidget(self._build_result_card(), 3)
        outer.addLayout(columns, 1)

    def _build_input_card(self) -> QFrame:
        card, lay = _make_card("Input image")

        self.format_combo = QComboBox()
        self.format_combo.addItems(OUTPUT_FORMATS.keys())  # JPG / HEIC
        lay.addLayout(_labeled("Convert format", self.format_combo))

        self.drop_zone = DropZone()
        self.drop_zone.fileSelected.connect(self._load_input)
        lay.addWidget(self.drop_zone, 1)

        self.paste_btn = QPushButton("Paste image")
        self.paste_btn.setMinimumHeight(40)
        self.paste_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.paste_btn.setToolTip("Use the image (or image / ZIP file) on the clipboard as the input")
        self.paste_btn.clicked.connect(self._paste_image)
        lay.addWidget(self.paste_btn)

        self.save_btn = QPushButton("Save Image")
        self.save_btn.setObjectName("primary")
        self.save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_btn.clicked.connect(self._on_save)
        lay.addWidget(self.save_btn)
        return card

    def _build_result_card(self) -> QFrame:
        card, lay = _make_card("Result")
        self.result_view = ResultView()
        self.result_view.message.connect(self.statusBar().showMessage)
        lay.addWidget(self.result_view, 1)
        lay.addWidget(_muted("Right-click the image and choose Copy."))
        return card

    def _build_right_column(self) -> QVBoxLayout:
        col = QVBoxLayout()
        col.setSpacing(16)

        # Metadata card
        meta, lay = _make_card("Metadata")
        self.inject_chk = QCheckBox("Inject Phone Metadata")  # unchecked by default
        self.inject_chk.setCursor(Qt.CursorShape.PointingHandCursor)
        lay.addWidget(self.inject_chk)

        phone_label = QLabel("Phone type")
        phone_label.setObjectName("fieldLabel")
        self.phone_combo = QComboBox()
        self.phone_combo.addItems(IPHONE_MODELS.keys())
        self.phone_combo.setCurrentText("iPhone 15 Pro")
        self.phone_combo.setMaxVisibleItems(10)
        lay.addLayout(_labeled(phone_label, self.phone_combo))
        lay.addWidget(_muted(
            "Writes the Make, Model and Software (iOS version) fields."))

        # Settings are disabled (and ignored on save) unless the box is ticked
        for w in (phone_label, self.phone_combo):
            w.setEnabled(False)
            self.inject_chk.toggled.connect(w.setEnabled)

        lay.addWidget(_separator())

        # Custom timestamp: 24-hour HH:mm (seconds are random) and a DD/MM/YYYY date.
        # Unchecked -> today's date and time are written instead.
        self.ts_chk = QCheckBox("Inject custom timestamp")  # unchecked by default
        self.ts_chk.setCursor(Qt.CursorShape.PointingHandCursor)
        lay.addWidget(self.ts_chk)

        time_label = QLabel("Time (24h)")
        time_label.setObjectName("fieldLabel")
        self.time_edit = QTimeEdit()
        self.time_edit.setDisplayFormat("HH:mm")
        self.time_edit.setWrapping(True)
        lay.addLayout(_labeled(time_label, self.time_edit))

        date_label = QLabel("Date (DD/MM/YYYY)")
        date_label.setObjectName("fieldLabel")
        self.date_edit = QDateEdit()
        self.date_edit.setDisplayFormat("dd/MM/yyyy")
        self.date_edit.setDateRange(QDate(YEAR_MIN, 1, 1), QDate(YEAR_MAX, 12, 31))
        self.date_edit.setCalendarPopup(True)
        lay.addLayout(_labeled(date_label, self.date_edit))

        lay.addWidget(_muted(
            "Always written to DateTime and DateTimeOriginal. Off: today's date and "
            "time. On: your date and time, with random seconds. In a ZIP, every photo "
            "is 1 minute after the previous one."))

        for w in (time_label, self.time_edit, date_label, self.date_edit):
            w.setEnabled(False)
            self.ts_chk.toggled.connect(w.setEnabled)
        col.addWidget(meta)

        # Output card
        out, lay = _make_card("Output")
        self.out_edit = QLineEdit()
        self.out_edit.setReadOnly(True)
        browse = QPushButton("Browse")
        browse.setCursor(Qt.CursorShape.PointingHandCursor)
        browse.clicked.connect(self._choose_out_dir)
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(self.out_edit, 1)
        row.addWidget(browse)
        lay.addLayout(_labeled("Output directory", row))
        lay.addWidget(_muted("Default: <app folder>/output. A folder you choose is remembered."))
        col.addWidget(out)
        self._refresh_out_edit()

        col.addStretch(1)
        return col

    # -- settings ----------------------------------------------------------
    def _restore_settings(self) -> None:
        """Apply saved values, then start persisting changes."""
        cfg = self._settings
        if cfg.output_format in OUTPUT_FORMATS:
            self.format_combo.setCurrentText(cfg.output_format)
        if cfg.phone_model in IPHONE_MODELS:
            self.phone_combo.setCurrentText(cfg.phone_model)
        self.inject_chk.setChecked(cfg.inject_metadata)

        saved_date = QDate.fromString(cfg.timestamp_date, "yyyy-MM-dd")
        self.date_edit.setDate(saved_date if saved_date.isValid() else QDate.currentDate())
        saved_time = QTime.fromString(cfg.timestamp_time, "HH:mm")
        if not saved_time.isValid():  # settings written by an older version had seconds
            saved_time = QTime.fromString(cfg.timestamp_time, "HH:mm:ss")
        self.time_edit.setTime(saved_time if saved_time.isValid() else QTime(12, 0))
        self.ts_chk.setChecked(cfg.inject_timestamp)

        self.format_combo.currentTextChanged.connect(self._persist)
        self.inject_chk.toggled.connect(self._persist)
        self.phone_combo.currentTextChanged.connect(self._persist)
        self.ts_chk.toggled.connect(self._persist)
        self.date_edit.dateChanged.connect(self._persist)
        self.time_edit.timeChanged.connect(self._persist)

    def _persist(self) -> None:
        """Collect the current UI state and write settings.json."""
        cfg = self._settings
        cfg.output_format = self.format_combo.currentText()
        cfg.inject_metadata = self.inject_chk.isChecked()
        cfg.phone_model = self.phone_combo.currentText()
        cfg.inject_timestamp = self.ts_chk.isChecked()
        cfg.timestamp_date = self.date_edit.date().toString("yyyy-MM-dd")
        cfg.timestamp_time = self.time_edit.time().toString("HH:mm")
        cfg.output_dir = str(self._custom_out_dir) if self._custom_out_dir else None
        if not self.isMaximized() and not self.isMinimized():
            cfg.window_width, cfg.window_height = self.width(), self.height()
        if not cfg.save():
            self.statusBar().showMessage("Could not write settings file.")

    # -- slots -------------------------------------------------------------
    @property
    def output_dir(self) -> Path:
        return self._custom_out_dir or default_output_dir()

    def _refresh_out_edit(self) -> None:
        self.out_edit.setText(str(self.output_dir))
        self.out_edit.setCursorPosition(0)
        self.out_edit.setToolTip(str(self.output_dir))

    def _load_input(self, path: str, display_name: str | None = None) -> None:
        """A dropped / chosen / pasted file: a single image or a ZIP of photos."""
        p = Path(path)
        if p.suffix.lower() == ZIP_EXTENSION:
            try:
                count = count_zip_images(p)
            except ProcessingError as exc:
                QMessageBox.warning(self, "Invalid ZIP", str(exc))
                return
            self._source = p
            plural = "photo" if count == 1 else "photos"
            self.drop_zone.set_loaded(p.name, self._zip_icon, f"ZIP loaded — {count} {plural} — click or drop another")
            self.statusBar().showMessage(f"Loaded ZIP: {p.name} ({count} {plural})")
            return
        try:
            src = validate_image(path)
            data, w, h = make_preview_rgba(src)
        except ProcessingError as exc:
            QMessageBox.warning(self, "Invalid image", str(exc))
            return
        except Exception as exc:  # preview failure must not block loading
            data, w, h = b"", 0, 0
            self.statusBar().showMessage(f"Preview unavailable: {exc}")
        preview = QImage(data, w, h, w * 4, QImage.Format.Format_RGBA8888).copy() if data else QImage()
        self._source = src
        shown = display_name or src.name
        self.drop_zone.set_loaded(shown, preview, "Image loaded — click or drop another image")
        self.statusBar().showMessage(f"Loaded: {shown}")

    def _paste_image(self) -> None:
        """Use the clipboard as the input: an image, or a copied image / ZIP file."""
        mime = QGuiApplication.clipboard().mimeData()
        if mime is not None:
            for url in mime.urls() if mime.hasUrls() else []:  # a file copied in Explorer
                local = Path(url.toLocalFile()) if url.isLocalFile() else None
                if local and local.suffix.lower() in SUPPORTED_EXTENSIONS | {ZIP_EXTENSION}:
                    self._load_input(str(local))
                    return
            if mime.hasImage():  # a picture copied from a browser, screenshot tool, editor...
                image = QGuiApplication.clipboard().image()
                if not image.isNull():
                    self._paste_clipboard_image(image)
                    return
        QMessageBox.information(self, "Nothing to paste",
                                "The clipboard does not contain an image or an image / ZIP file.")

    def _paste_clipboard_image(self, image: QImage) -> None:
        """Store the clipboard picture losslessly in a temp PNG and load it like a file."""
        old = getattr(self, "_paste_dir", None)
        self._paste_dir = tempfile.TemporaryDirectory(prefix="metatool_paste_")
        target = Path(self._paste_dir.name) / "pasted_image.png"
        if not image.save(str(target), "PNG", 20):  # 20 = fast compression; it is only a temp file
            QMessageBox.warning(self, "Paste failed", "The clipboard image could not be read.")
            return
        if old is not None:
            old.cleanup()
        self._load_input(str(target), "Pasted image")

    def _choose_out_dir(self) -> None:
        current = self.output_dir
        start = str(current if current.exists() else current.parent)
        folder = QFileDialog.getExistingDirectory(self, "Select output folder", start)
        if folder:
            self._custom_out_dir = Path(folder)
            self._refresh_out_edit()
            self._persist()

    def _on_save(self) -> None:
        if self._source is None:
            QMessageBox.information(self, "No image", "Please drop or select an image or ZIP first.")
            return
        if self._worker and self._worker.isRunning():
            return
        self._persist()
        model = self.phone_combo.currentText() if self.inject_chk.isChecked() else None
        timestamp = None
        if self.ts_chk.isChecked():
            d, t = self.date_edit.date(), self.time_edit.time()
            timestamp = custom_timestamp(date(d.year(), d.month(), d.day()), t.hour(), t.minute())
        self._custom_timestamp = timestamp is not None

        self.save_btn.setEnabled(False)
        self.statusBar().showMessage("Processing…")
        self._worker = SaveWorker(
            self._source, self.output_dir, self.format_combo.currentText(), model, timestamp)
        self._worker.progress.connect(
            lambda done, total: self.statusBar().showMessage(f"Processing {min(done + 1, total)}/{total}…"))
        self._worker.succeeded.connect(self._on_success)
        self._worker.failed.connect(self._on_failure)
        self._worker.finished.connect(lambda: self.save_btn.setEnabled(True))
        self._worker.start()

    def _on_success(self, result: SaveResult | BatchResult) -> None:
        if isinstance(result, BatchResult):
            self._on_batch_success(result)
            return
        self.statusBar().showMessage(f"Saved: {result.path}")
        self._show_result_preview(result)
        report = result.report
        lines = [f"Image saved successfully:\n{result.path}"]
        if result.phone_injected:
            lines.append("Phone metadata injected.")
        kind = "custom" if self._custom_timestamp else "today's date and time"
        lines.append(f"Timestamp ({kind}): {result.timestamp:%Y-%m-%d %H:%M:%S}")
        lines.append(self._pixel_status(result))

        icon, title = QMessageBox.Icon.Information, "Success"
        if result.max_error:
            icon, title = QMessageBox.Icon.Warning, "Saved - not bit-identical"
        if report is not None:
            if report.passed:
                lines.append(f"✔ Verified: {report.summary()}")
            else:
                icon, title = QMessageBox.Icon.Warning, "Saved - verification found problems"
                problems = "; ".join(c.name for c in report.errors[:3])
                lines.append(f"✘ Verification found {len(report.errors)} problem(s): {problems}")
        box = QMessageBox(icon, title, "\n\n".join(lines), QMessageBox.StandardButton.Ok, self)
        if report is not None:
            box.setDetailedText(report.text() + self._icc_note(result.icc_removed))  # every check
        box.exec()

    @staticmethod
    def _pixel_status(r: SaveResult) -> str:
        """One line telling the truth about what encoding did to the pixels."""
        if r.max_error:
            return (f"⚠ Pixels: not bit-identical - largest difference {r.max_error}/255 per channel "
                    "(JPG cannot store this image exactly; HEIC can)")
        how = ("lossless copy, nothing re-encoded" if r.lossless_copy
               else "lossless HEIC" if r.path.suffix.lower() == ".heic" else "lossless")
        if r.pixel_notes:
            return f"ℹ Pixels: identical after conversion - {'; '.join(r.pixel_notes)}"
        return f"✔ Pixels: identical to the original ({how})"

    @staticmethod
    def _icc_note(removed: bool) -> str:
        return ("\n\nℹ The source's ICC colour profile was removed (as intended); colours can look "
                "different in colour-managed viewers.") if removed else ""

    def _show_result_preview(self, result: SaveResult) -> None:
        """Display the processed (saved) image in the Result card."""
        try:
            data, w, h = make_preview_rgba(result.path, 1400)
            preview = QImage(data, w, h, w * 4, QImage.Format.Format_RGBA8888).copy()
        except Exception as exc:
            self.statusBar().showMessage(f"Saved, but the preview failed: {exc}")
            preview = QImage()
        self.result_view.show_image(preview, result.path, f"{result.timestamp:%Y-%m-%d %H:%M:%S}")

    def _on_batch_success(self, batch: BatchResult) -> None:
        total = len(batch.results) + len(batch.failures)
        self.statusBar().showMessage(f"Saved {len(batch.results)} of {total} images to {batch.folder}")
        self.result_view.show_zip(
            self._zip_icon, f"{len(batch.results)} of {total} images saved to “{batch.folder.name}”")

        lines = [f"Saved {len(batch.results)} of {total} images to:\n{batch.folder}"]
        if batch.failures:
            shown = "; ".join(f"{n} ({why})" for n, why in batch.failures[:3])
            more = f" and {len(batch.failures) - 3} more" if len(batch.failures) > 3 else ""
            lines.append(f"⚠ {len(batch.failures)} file(s) could not be processed: {shown}{more}")
        if batch.results:
            if self.inject_chk.isChecked():
                lines.append("Phone metadata injected.")
            first, last = batch.results[0].timestamp, batch.results[-1].timestamp
            kind = "custom start" if self._custom_timestamp else "ending now"
            lines.append(f"Timestamps ({kind}): {first:%Y-%m-%d %H:%M:%S} → {last:%Y-%m-%d %H:%M:%S}, 1 minute apart")
        if batch.results:
            exact = sum(1 for r in batch.results if not r.max_error and not r.pixel_notes)
            worst = max(r.max_error for r in batch.results)
            if exact == len(batch.results):
                lines.append(f"✔ Pixels: identical to the originals in all {exact} images")
            else:
                lines.append(f"⚠ Pixels: {len(batch.results) - exact} of {len(batch.results)} images are not bit-identical"
                             + (f" (largest difference {worst}/255)" if worst else " (see the details)"))
        bad = [r for r in batch.results if r.report is not None and not r.report.passed]
        icon, title = QMessageBox.Icon.Information, "Success"
        if bad:
            icon, title = QMessageBox.Icon.Warning, "Saved - verification found problems"
            lines.append(f"✘ Verification found problems in {len(bad)} image(s) - see the details")
        elif batch.results:
            checks = batch.results[0].report.summary().split(" ")[0].split("/")[1] if batch.results[0].report else "?"
            lines.append(f"✔ Verified: all {len(batch.results)} images passed {checks}/{checks} checks")
        if batch.failures and icon == QMessageBox.Icon.Information:
            icon, title = QMessageBox.Icon.Warning, "Saved with some skipped files"
        box = QMessageBox(icon, title, "\n\n".join(lines), QMessageBox.StandardButton.Ok, self)
        box.setDetailedText(self._batch_details(batch)
                            + self._icc_note(any(r.icc_removed for r in batch.results)))
        box.exec()

    @staticmethod
    def _batch_details(batch: BatchResult) -> str:
        out = [f"Folder: {batch.folder}", ""]
        for r in batch.results:
            ok = r.report is not None and r.report.passed
            out.append(f"{'✔' if ok else '✘'} {r.source_name} → {r.path.name} · {r.timestamp:%Y-%m-%d %H:%M:%S}"
                       f" · {r.report.summary() if r.report else 'not verified'}")
            if r.max_error or r.pixel_notes:
                out.append("    " + MainWindow._pixel_status(r))
            if r.report is not None:
                out += [f"    ✘ {c.name} - {c.detail}" for c in r.report.errors]
        if batch.failures:
            out += ["", "Could not be processed:"] + [f"  • {n} - {why}" for n, why in batch.failures]
        if batch.skipped:
            out += ["", f"{batch.skipped} entr{'y' if batch.skipped == 1 else 'ies'} ignored (folders, non-image files)."]
        notes = batch.results[0].report.notes if batch.results and batch.results[0].report else []
        if notes:
            out += ["", "ℹ Still different from a genuine iPhone capture (not changed by this tool):"]
            out += [f"  • {n}" for n in notes]
        return "\n".join(out)

    def _on_failure(self, message: str) -> None:
        self.statusBar().showMessage("Save failed.")
        QMessageBox.critical(self, "Error", message)

    def closeEvent(self, event) -> None:
        if self._worker and self._worker.isRunning():
            self._worker.wait()
        self._persist()
        if getattr(self, "_paste_dir", None) is not None:
            self._paste_dir.cleanup()
        super().closeEvent(event)