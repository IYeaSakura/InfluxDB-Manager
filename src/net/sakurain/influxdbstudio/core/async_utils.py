"""Run blocking work (HTTP calls) off the UI thread.

Replaces the C# ``async/await`` pattern: blocking client methods are executed
on a ``ThreadPoolExecutor`` and results are delivered back to the Qt event
loop via a queued signal.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, Optional

from PySide6.QtCore import QObject, Signal

_executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="influxdb")


class _Delivery(QObject):
    """Queued-signal bridge between worker threads and the GUI thread."""

    delivered = Signal(object, object, object)  # token, result, exception
    busy_changed = Signal(int)  # number of in-flight background requests


_delivery = _Delivery()
_pending: Dict[int, tuple] = {}
_token_counter = 0
_busy_count = 0


def busy_count() -> int:
    """Number of background requests currently in flight."""
    return _busy_count


def is_busy() -> bool:
    return _busy_count > 0


def _on_delivered(token: int, result: object, error: object) -> None:
    global _busy_count
    entry = _pending.pop(token, None)
    _busy_count -= 1
    if _busy_count <= 0:
        _busy_count = 0
        _delivery.busy_changed.emit(0)
    else:
        _delivery.busy_changed.emit(_busy_count)
    if entry is None:
        return
    on_success, on_error = entry
    if error is not None:
        if on_error is not None:
            on_error(error)
    elif on_success is not None:
        on_success(result)


_delivery.delivered.connect(_on_delivered)


def run_async(fn: Callable[[], Any],
              on_success: Optional[Callable[[Any], None]] = None,
              on_error: Optional[Callable[[BaseException], None]] = None) -> None:
    """Run ``fn`` on a background thread; deliver ``fn()`` to ``on_success``
    (or the raised exception to ``on_error``) on the GUI thread."""

    global _token_counter, _busy_count
    _token_counter += 1
    token = _token_counter
    _pending[token] = (on_success, on_error)
    was_idle = _busy_count == 0
    _busy_count += 1
    if was_idle:
        _delivery.busy_changed.emit(1)

    def worker() -> None:
        try:
            result: Any = fn()
            error: Any = None
        except BaseException as ex:  # noqa: BLE001 - delivered to UI layer
            result, error = None, ex
        _delivery.delivered.emit(token, result, error)

    _executor.submit(worker)
