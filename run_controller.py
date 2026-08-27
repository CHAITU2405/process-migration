"""Laptop 1. The machine you sit at.

    python run_controller.py
"""
from __future__ import annotations

import sys


def main() -> int:
    if sys.platform != "win32":
        print("The controller uses Win32 APIs and only runs on Windows.")
        return 1

    from appmig.winapi.dpi import enable_dpi_awareness
    enable_dpi_awareness()

    from PySide6.QtWidgets import QApplication

    from appmig import config
    from appmig.ui import theme
    from appmig.ui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName(config.APP_NAME)
    app.setStyleSheet(theme.STYLESHEET)

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
