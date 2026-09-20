"""Background work for a Tk window, and a watchdog that reports when the Tk thread stops answering."""

from __future__ import annotations

import queue
import sys
import threading
import time
import tkinter as tk
import traceback
from collections.abc import Callable
from typing import Any

Work = Callable[[], Any]
Done = Callable[[Any], None]


def completion_ping(root: Any) -> None:
    """Play the system notification sound from a completion callback on the Tk thread."""
    try:
        root.bell()
    except tk.TclError:
        pass  # Closing the window must not turn a completed request into an error.


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
        try:
            self.drain()
        finally:
            # A Tk callback error enters recovery; its completion still needs this queue.
            self.root.after(self.interval, self._poll)


class Watchdog:
    """Notices when the Tk thread stops answering and writes every thread's stack through ``on_stall``.

    The Tk thread beats every ``beat_ms`` through ``after``; a daemon thread checks the beat and reports a stall
    once when it begins and then every ``repeat_seconds`` while it lasts.
    """

    def __init__(self, root: Any, on_stall: Callable[[str], None], stall_seconds: float = 5.0,
                 beat_ms: int = 500, repeat_seconds: float = 30.0) -> None:
        self.root = root
        self.on_stall = on_stall
        self.stall_seconds = stall_seconds
        self.beat_ms = beat_ms
        self.repeat_seconds = repeat_seconds
        self.last_beat = time.monotonic()
        self.ui_thread = threading.get_ident()
        self.reported_at: float | None = None
        root.after(beat_ms, self._beat)
        threading.Thread(target=self._watch, daemon=True, name="icoda-watchdog").start()

    def _beat(self) -> None:
        self.last_beat = time.monotonic()
        self.root.after(self.beat_ms, self._beat)

    def _watch(self) -> None:
        while True:
            time.sleep(1.0)
            silence = time.monotonic() - self.last_beat
            if silence < self.stall_seconds:
                self.reported_at = None
                continue
            if self.reported_at is None or time.monotonic() - self.reported_at >= self.repeat_seconds:
                self.reported_at = time.monotonic()
                self.on_stall(f"the window has not answered for {silence:.0f} s\n" + self.stacks())

    def stacks(self) -> str:
        """Every thread's stack, the Tk thread first."""
        names = {t.ident: t.name for t in threading.enumerate()}
        frames = sys._current_frames()
        ordered = [self.ui_thread, *(i for i in frames if i != self.ui_thread)]
        parts = []
        for ident in ordered:
            frame = frames.get(ident)
            if frame is None:
                continue
            label = "Tk thread" if ident == self.ui_thread else names.get(ident, str(ident))
            parts.append(f"--- {label}\n" + "".join(traceback.format_stack(frame)))
        return "\n".join(parts)
