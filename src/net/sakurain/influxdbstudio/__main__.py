"""Application entry point."""
from __future__ import annotations

import logging
import sys


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    from pathlib import Path

    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from . import __version__, app as app_module
    from .core.settings import AppSettings
    from .i18n import set_language, tr
    from .ui.main_window import MainWindow

    qapp = QApplication(sys.argv)
    qapp.setApplicationName("InfluxDB Manager")
    qapp.setApplicationDisplayName("InfluxDB Manager")
    qapp.setOrganizationName("InfluxDBStudio")

    # Application / taskbar icon (sakurain.ico). On Windows the taskbar icon
    # additionally requires an explicit AppUserModelID.
    icon_path = Path(__file__).resolve().parent / "resources" / "sakurain.ico"
    if icon_path.exists():
        qapp.setWindowIcon(QIcon(str(icon_path)))
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "net.sakurain.InfluxDBManager")
        except Exception:
            pass

    # Initialize global settings
    settings = AppSettings(version=__version__)
    settings.load_all()
    app_module.settings = settings
    set_language(settings.language)

    window = MainWindow()
    window.setWindowIcon(qapp.windowIcon())
    window.show()
    return qapp.exec()


if __name__ == "__main__":
    sys.exit(main())
