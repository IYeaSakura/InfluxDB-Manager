"""Application-level shared state (port of the AppForm static members)."""
from __future__ import annotations

import logging
from typing import List, Optional

from .core.client import InfluxDbClient
from .core.settings import AppSettings
from .i18n import tr

log = logging.getLogger("net.sakurain.influxdbstudio.app")

#: Global application settings (initialized in ``__main__``).
settings: AppSettings = AppSettings()

#: Currently active InfluxDB clients (one per open connection).
active_clients: List[InfluxDbClient] = []

#: Main window singleton (set by MainWindow itself).
main_window = None


def set_status(text: str) -> None:
    if main_window is not None:
        main_window.set_status(text)


def display_error(message: str, caption: str = None, parent=None) -> None:
    from .ui.common import display_error as _display_error
    if caption is None:
        caption = tr("error")
    _display_error(message, caption, parent or main_window)


def display_exception(ex: BaseException, caption: str = None, parent=None) -> None:
    from .ui.common import display_exception as _display_exception
    _display_exception(ex, caption, parent or main_window)


def run_backfill_command() -> None:
    """Static entry used by the ContinuousQueryControl backfill button
    (port of ``AppForm.RunBackFill()``)."""
    if main_window is None:
        return
    main_window.run_backfill_for_selected_node()
