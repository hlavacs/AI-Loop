"""Background work for a Tk window: run a callable in a thread, deliver its result (or exception) on the Tk thread."""

from __future__ import annotations

import queue
import threading
import traceback
from collections.abc import Callable
from typing import Any

Work = Callable[[], Any]
Done = Callable[[Any], None]


class UiTasks:
    """``run_async`` starts the work; ``done`` is called from the Tk thread with the result or the exception."""

    def __init__(self, root: Any, on_failure: Callable[[str], None] | None = None, interval: int = 100) -> None:
        self.root = root
        self.on_failure = on_failure
        self.interval = interval
        self.queue: queue.Queue[tuple[Callable[..., None], tuple[Any, ...]]] = queue.Queue()
        root.after(interval, self._poll)

    def run_async(self, work: Work, done: Done) -> threading.Thread:
        def target() -> None:
            try:
                result = work()
            except Exception as exc:  # noqa: BLE001  (delivered to the caller; the traceback is logged)
                if self.on_failure is not None:
                    self.on_failure(traceback.format_exc())
                result = exc
            self.queue.put((done, (result,)))

        thread = threading.Thread(target=target, daemon=True)
        thread.start()
        return thread

    def run_on_ui(self, func: Callable[..., None], *args: Any) -> None:
        """Call ``func(*args)`` on the Tk thread soon (safe from any thread)."""
        self.queue.put((func, args))

    def drain(self) -> None:
        """Run every callback that is waiting."""
        while True:
            try:
                func, args = self.queue.get_nowait()
            except queue.Empty:
                return
            func(*args)

    def _poll(self) -> None:
        self.drain()
        self.root.after(self.interval, self._poll)
