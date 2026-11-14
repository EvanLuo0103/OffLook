"""Asynchronous configurable Windows hotkey listener without Tk, COM, or file access.

Call ``start``/``stop`` from the controller and drain plain dictionaries with
``poll``. Registration outcomes are retained separately from the one pending
hotkey, so a busy UI cannot lose a registration failure to a key press.
"""

from __future__ import annotations

import queue
import sys
import threading
from typing import Any

from offlook.core.hotkeys import parse_hotkey


class HotkeyListener:
    """Own one message thread; report ready/error/hotkey events through ``poll``.

    Construction does not import Windows modules or register a shortcut.
    ``start`` and ``stop`` are asynchronous and idempotent while running/stopping.
    Errors are delivered as dictionaries rather than raised on the message thread.
    """

    def __init__(self, combo: str = "Ctrl+Space") -> None:
        """Validate a shortcut and create an initially stopped single-slot listener."""
        self._spec = parse_hotkey(combo)
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop_requested = threading.Event()
        self._stopped = threading.Event()
        self._stopped.set()
        self._thread_id: int | None = None
        self._queue_ready = False
        self._quit_posted = False
        self._gui: Any = None
        self._status: queue.SimpleQueue[dict[str, object]] = queue.SimpleQueue()
        self._keys: queue.Queue[dict[str, object]] = queue.Queue(maxsize=1)

    @property
    def combo(self) -> str:
        """Return the canonical registered shortcut; immutable for this listener."""
        return self._spec.canonical

    @property
    def is_stopped(self) -> bool:
        """Return whether the message thread has finished unregistering its key."""
        with self._lock:
            return self._stopped.is_set() and (
                self._thread is None or not self._thread.is_alive()
            )

    def start(self) -> None:
        """Start registration without waiting; retain its ready/error event.

        A call during an existing run, including its shutdown, has no effect.
        Thread-start errors are reported through ``poll`` as ordinary errors.
        """
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_requested.clear()
            self._stopped.clear()
            self._queue_ready = False
            self._quit_posted = False
            self._thread_id = None
            self._gui = None
            self._discard_keys()
            self._thread = threading.Thread(
                target=self._listen, name="OffLookHotkey", daemon=True
            )
            try:
                self._thread.start()
            except Exception as exc:
                self._stopped.set()
                self._error("Cannot start the hotkey thread", exc)

    def stop(self) -> None:
        """Request stop without joining; post WM_QUIT only after queue creation.

        A failed PostThreadMessage is reported, not silently treated as stopped.
        Calling stop again may retry a failed post while the thread remains alive.
        """
        self._stop_requested.set()
        with self._lock:
            if (
                not self._queue_ready
                or self._thread_id is None
                or self._quit_posted
            ):
                return
            try:
                self._gui.PostThreadMessage(self._thread_id, 0x0012, 0, 0)
                self._quit_posted = True
            except Exception as exc:
                self._error("Cannot notify the hotkey thread to stop", exc)

    def poll(self) -> list[dict[str, object]]:
        """Return pending statuses followed by at most one key, without waiting.

        ``ready`` means registration succeeded; ``error`` includes ``message``;
        ``hotkey`` includes the foreground HWND captured at message receipt.
        Every event includes this listener's canonical ``combo``.
        Keys pending at shutdown are discarded, but registration results survive.
        """
        events: list[dict[str, object]] = []
        while True:
            try:
                events.append(self._status.get_nowait())
            except queue.Empty:
                break
        try:
            key = self._keys.get_nowait()
        except queue.Empty:
            pass
        else:
            if not self._stop_requested.is_set():
                events.append(key)
        return events

    def _discard_keys(self) -> None:
        """Discard the pending key, if any; never discard registration statuses."""
        try:
            self._keys.get_nowait()
        except queue.Empty:
            pass

    def _error(self, message: str, exc: Exception) -> None:
        """Retain a bounded diagnostic including the original Win32 error text."""
        self._status.put({
            "type": "error", "combo": self.combo, "message": f"{message}：{exc}"[:512],
        })

    def _listen(self) -> None:
        """Register, capture foreground handles, and unregister on this thread.

        No callbacks, COM calls, Tk operations, or file operations run here.
        All Windows/import failures become retained error notifications.
        """
        registered = False
        gui: Any = None
        try:
            if sys.platform != "win32":
                raise RuntimeError("OffLook currently supports only Windows")
            import win32api
            import win32gui

            gui = win32gui
            gui.PeekMessage(0, 0x0400, 0x0400, 0)
            with self._lock:
                self._thread_id = win32api.GetCurrentThreadId()
                self._gui = gui
                self._queue_ready = True
            if self._stop_requested.is_set():
                return
            try:
                gui.RegisterHotKey(None, 1, self._spec.modifiers | 0x4000, self._spec.virtual_key)
            except Exception as exc:
                self._error(
                    f"Failed to register {self.combo}; it may be in use by an input method or another program", exc
                )
                return
            registered = True
            self._status.put({"type": "ready", "combo": self.combo})
            while not self._stop_requested.is_set():
                result, message = gui.GetMessage(0, 0, 0)
                if result == 0:
                    break
                if result == -1:
                    raise RuntimeError("GetMessage failed")
                if message[1] == 0x0312 and message[2] == 1:
                    foreground_hwnd = int(gui.GetForegroundWindow())
                    if not self._stop_requested.is_set():
                        try:
                            self._keys.put_nowait(
                                {"type": "hotkey", "combo": self.combo,
                                 "foreground_hwnd": foreground_hwnd}
                            )
                        except queue.Full:
                            pass
        except Exception as exc:
            self._error(f"Hotkey listener failed for {self.combo}", exc)
        finally:
            if registered:
                try:
                    gui.UnregisterHotKey(None, 1)
                except Exception as exc:
                    self._error(f"Failed to unregister {self.combo}", exc)
            with self._lock:
                self._queue_ready = False
                self._thread_id = None
                self._gui = None
                self._discard_keys()
                self._stopped.set()
