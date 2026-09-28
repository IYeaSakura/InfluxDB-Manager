"""Application entry point."""
from __future__ import annotations

import logging
import os
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
    from .ui.common import resource_path
    from .ui.main_window import MainWindow

    qapp = QApplication(sys.argv)
    qapp.setApplicationName("InfluxDB Manager")
    qapp.setApplicationDisplayName("InfluxDB Manager")
    qapp.setOrganizationName("InfluxDBStudio")

    # Application / taskbar icon (sakurain.png; PNG is built into QtGui and
    # works in trimmed PyInstaller bundles without the qico image plugin).
    # On Windows the taskbar icon additionally requires an explicit
    # AppUserModelID.
    icon_file = Path(resource_path("sakurain.png"))
    if icon_file.exists():
        qapp.setWindowIcon(QIcon(str(icon_file)))
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

    # Self-test mode (used by packaging tests): report whether the app icon
    # resolved, then exit without entering the event loop.
    if os.environ.get("INFLUXDB_MANAGER_SELFTEST"):
        ok = not qapp.windowIcon().isNull()
        print(f"SELFTEST icon_loaded={ok} icon_file={icon_file} "
              f"exists={icon_file.exists()}")
        return 0 if ok else 1

    window.show()
    return qapp.exec()


if __name__ == "__main__":
    sys.exit(main())
