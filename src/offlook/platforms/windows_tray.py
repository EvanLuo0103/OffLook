"""Native Windows notification-area icon with queued, Tk-free UI requests.

Construct ``TrayIcon``, call ``start()``, and drain ``poll()`` on the UI thread.
Both lifecycle methods return without waiting for the native message thread.
"""

from __future__ import annotations

import queue
import sys
import threading
from typing import Any


class TrayIcon:
    """Own a hidden window and deliver ``show``, ``exit``, and ``error`` events.

    ``last_error`` holds the most recent Traditional Chinese diagnostic, or an
    empty string before any failure. Windows modules are imported only by the
    dedicated thread. Construction does not create windows or touch Tk.
    """

    _ICON_ID = 1
    _CALLBACK = 0x8001  # WM_APP + 1
    _SHOW = 1
    _EXIT = 2

    def __init__(self) -> None:
        """Create an initially stopped icon without importing Windows modules."""
        self.last_error = ""
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop_requested = threading.Event()
        self._stopped = threading.Event()
        self._stopped.set()
        self._events: queue.SimpleQueue[str] = queue.SimpleQueue()
        self._queue_ready = False
        self._wake_handle: Any = None
        self._event_api: Any = None
        self._gui: Any = None
        self._con: Any = None
        self._hwnd: int | None = None
        self._icon: Any = None
        self._taskbar_created = 0

    @property
    def is_stopped(self) -> bool:
        """Return true only after native resources and the thread are released."""
        with self._lock:
            return self._stopped.is_set() and (
                self._thread is None or not self._thread.is_alive()
            )

    def start(self) -> None:
        """Start asynchronously; calls during an existing run are harmless.

        Startup and native failures are reported by ``poll()``, not raised on
        the caller's UI thread. A completed instance may be started again.
        """
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            for event in self.poll():
                if event == "error":
                    self._events.put(event)
            self._stop_requested.clear()
            self._stopped.clear()
            self._queue_ready = False
            self._thread = threading.Thread(
                target=self._run, name="OffLookTray", daemon=True
            )
            try:
                self._thread.start()
            except Exception as exc:
                self._stopped.set()
                self._error("Cannot start the notification area icon thread", exc)

    def stop(self) -> None:
        """Request shutdown without joining, including during thread startup.

        A native event wakes the message loop only after its ready handshake.
        WM_CANCELMODE also dismisses an open native menu. A bounded wait in the
        loop guarantees it notices the Python stop flag even if waking fails.
        """
        with self._lock:
            self._stop_requested.set()
            if not self._queue_ready:
                return
            try:
                self._event_api.SetEvent(self._wake_handle)
            except Exception as exc:
                self._error("Cannot wake the notification area icon thread to stop it", exc)
            if self._hwnd is not None:
                try:
                    self._gui.PostMessage(self._hwnd, self._con.WM_CANCELMODE, 0, 0)
                except Exception as exc:
                    self._error("Cannot close the notification area icon menu", exc)

    def poll(self) -> list[str]:
        """Drain pending ``show``/``exit``/``error`` strings without waiting.

        Read ``last_error`` for error details. Show and exit events queued
        before shutdown are discarded while stopping; errors remain visible.
        """
        events: list[str] = []
        while True:
            try:
                event = self._events.get_nowait()
            except queue.Empty:
                return events
            if event == "error" or not self._stop_requested.is_set():
                events.append(event)

    def _error(self, message: str, exc: Exception) -> None:
        """Retain a bounded diagnostic and queue an error without calling Tk."""
        self.last_error = f"{message}：{exc}"[:512]
        self._events.put("error")

    def _add_icon(self) -> None:
        """Add or restore the system-owned application icon; propagate errors."""
        self._gui.Shell_NotifyIcon(
            self._gui.NIM_ADD,
            (
                self._hwnd,
                self._ICON_ID,
                self._gui.NIF_MESSAGE | self._gui.NIF_ICON | self._gui.NIF_TIP,
                self._CALLBACK,
                self._icon,
                "OffLook File Preview",
            ),
        )

    def _show_menu(self, hwnd: int) -> None:
        """Display a native context menu and queue its action; always free it."""
        gui, con = self._gui, self._con
        menu = gui.CreatePopupMenu()
        try:
            gui.AppendMenu(menu, con.MF_STRING, self._SHOW, "Open Control Window")
            gui.AppendMenu(menu, con.MF_STRING, self._EXIT, "Exit")
            gui.SetForegroundWindow(hwnd)
            x, y = gui.GetCursorPos()
            command = gui.TrackPopupMenu(
                menu,
                con.TPM_RETURNCMD | con.TPM_NONOTIFY | con.TPM_RIGHTBUTTON,
                x,
                y,
                0,
                hwnd,
                None,
            )
            if not self._stop_requested.is_set():
                if command == self._SHOW:
                    self._events.put("show")
                elif command == self._EXIT:
                    self._events.put("exit")
        finally:
            try:
                gui.PostMessage(hwnd, con.WM_NULL, 0, 0)
            finally:
                gui.DestroyMenu(menu)

    def _window_proc(self, hwnd: int, message: int, wparam: int, lparam: int) -> int:
        """Handle native tray messages on the owning thread, never invoking Tk."""
        gui, con = self._gui, self._con
        try:
            if message == self._taskbar_created:
                if not self._stop_requested.is_set():
                    self._add_icon()
                return 0
            if message == self._CALLBACK and wparam == self._ICON_ID:
                if self._stop_requested.is_set():
                    return 0
                if lparam == con.WM_LBUTTONDBLCLK:
                    self._events.put("show")
                elif lparam in (con.WM_RBUTTONUP, con.WM_CONTEXTMENU):
                    self._show_menu(hwnd)
                return 0
            if message == con.WM_DESTROY:
                gui.PostQuitMessage(0)
                return 0
            return gui.DefWindowProc(hwnd, message, wparam, lparam)
        except Exception as exc:
            self._error("Notification area icon message handling failed", exc)
            return 0

    def _run(self) -> None:
        """Create, pump, and finally release all thread-owned native resources.

        The queue-ready handshake and stop flag cover stop-before-start races.
        A stop event interrupts idle waits; bounded waits additionally tolerate
        wake failures. No COM, Tk, file access, or application callback runs here.
        """
        gui: Any = None
        instance: Any = None
        wake_handle: Any = None
        hwnd: int | None = None
        class_name = ""
        class_registered = False
        icon_added = False
        try:
            if sys.platform != "win32":
                raise RuntimeError("OffLook currently supports only Windows")
            import win32api
            import win32con
            import win32event
            import win32gui

            gui = win32gui
            self._gui, self._con = gui, win32con
            wake_handle = win32event.CreateEvent(None, True, False, None)
            gui.PeekMessage(0, win32con.WM_USER, win32con.WM_USER, win32con.PM_NOREMOVE)
            with self._lock:
                self._event_api = win32event
                self._wake_handle = wake_handle
                self._queue_ready = True
            if self._stop_requested.is_set():
                return
            self._taskbar_created = gui.RegisterWindowMessage("TaskbarCreated")
            instance = win32api.GetModuleHandle(None)
            class_name = f"OffLookTray_{win32api.GetCurrentProcessId()}_{id(self):x}"
            window_class = gui.WNDCLASS()
            window_class.hInstance = instance
            window_class.lpszClassName = class_name
            window_class.lpfnWndProc = self._window_proc
            gui.RegisterClass(window_class)
            class_registered = True
            # A hidden top-level window receives Explorer's TaskbarCreated
            # broadcast; a message-only window would not receive it.
            hwnd = gui.CreateWindowEx(
                0, class_name, "OffLook", 0, 0, 0, 0, 0, 0, 0, instance, None
            )
            with self._lock:
                self._hwnd = hwnd
            if self._stop_requested.is_set():
                return
            self._icon = gui.LoadIcon(0, win32con.IDI_APPLICATION)
            self._add_icon()
            icon_added = True
            while not self._stop_requested.is_set():
                result = win32event.MsgWaitForMultipleObjects(
                    (wake_handle,), False, 100, win32con.QS_ALLINPUT
                )
                if result == win32event.WAIT_OBJECT_0:
                    break
                if result == win32event.WAIT_OBJECT_0 + 1:
                    if gui.PumpWaitingMessages():
                        break
                elif result != win32event.WAIT_TIMEOUT:
                    raise RuntimeError(f"Notification area icon message wait failed ({result})")
        except Exception as exc:
            self._error("The notification area icon cannot operate", exc)
        finally:
            # Invalidate the ready handshake before closing handles. stop()
            # cannot race SetEvent/PostMessage against the cleanup below.
            with self._lock:
                self._queue_ready = False
                self._wake_handle = None
                self._event_api = None
                self._hwnd = None
            if icon_added:
                try:
                    gui.Shell_NotifyIcon(gui.NIM_DELETE, (hwnd, self._ICON_ID))
                except Exception as exc:
                    self._error("Cannot remove the notification area icon", exc)
            if hwnd is not None:
                try:
                    if gui.IsWindow(hwnd):
                        gui.DestroyWindow(hwnd)
                except Exception as exc:
                    self._error("Cannot destroy the hidden notification area window", exc)
            if class_registered:
                try:
                    gui.UnregisterClass(class_name, instance)
                except Exception as exc:
                    self._error("Cannot unregister the notification area window class", exc)
            if wake_handle is not None:
                try:
                    wake_handle.Close()
                except Exception as exc:
                    self._error("Cannot release the notification area stop event", exc)
            self._icon = None  # LoadIcon returns a shared icon: do not destroy it.
            self._gui = None
            self._con = None
            self._stopped.set()
