"""Entry point: python main.py"""

import sys

from PyQt6.QtWidgets import QApplication

from core.theme import apply_theme, enable_dark_titlebar
from core.ui import MainWindow


def main() -> None:
    if sys.platform == "win32":
        # Own taskbar identity so Windows shows our icon instead of python.exe's
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("MetaTool.App")
        except Exception:
            pass

    app = QApplication(sys.argv)
    apply_theme(app)  # dark theme + window icon (icon.ico) for every window
    window = MainWindow()
    enable_dark_titlebar(window)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
