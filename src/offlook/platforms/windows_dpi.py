"""Initialize process DPI awareness before any Tk or native application windows."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import sys

from offlook.core.errors import OffLookError


_ACCESS_DENIED = 5
_E_ACCESSDENIED = 0x80070005


def enable_high_dpi() -> None:
    """Prefer per-monitor v2 awareness, preserving a mode already chosen by the host."""
    if sys.platform != "win32":
        return
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    modern = getattr(user32, "SetProcessDpiAwarenessContext", None)
    if modern is not None:
        modern.argtypes = [ctypes.c_void_p]
        modern.restype = wintypes.BOOL
        ctypes.set_last_error(0)
        # Awareness must be chosen before Tk creates even its hidden native windows.
        if modern(ctypes.c_void_p(-4)):
            return
        error = ctypes.get_last_error()
        if error == _ACCESS_DENIED:
            return
        raise OffLookError(f"Cannot enable high-DPI display (Windows error {error})")
    try:
        shcore = ctypes.WinDLL("shcore", use_last_error=True)
    except OSError:
        shcore = None
    per_monitor = getattr(shcore, "SetProcessDpiAwareness", None)
    if per_monitor is not None:
        per_monitor.argtypes = [ctypes.c_int]
        per_monitor.restype = ctypes.c_long
        result = per_monitor(2)
        if result == 0 or result & 0xFFFFFFFF == _E_ACCESSDENIED:
            return
        raise OffLookError(f"Cannot enable high-DPI display (Windows status 0x{result & 0xFFFFFFFF:08X})")
    legacy = getattr(user32, "SetProcessDPIAware", None)
    if legacy is not None:
        legacy.argtypes = []
        legacy.restype = wintypes.BOOL
        ctypes.set_last_error(0)
        if legacy() or ctypes.get_last_error() == _ACCESS_DENIED:
            return
        raise OffLookError(f"Cannot enable high-DPI display (Windows error {ctypes.get_last_error()})")


def window_dpi(hwnd: int) -> int:
    """Return a window's physical DPI, with a matched desktop-DC fallback on old Windows."""
    if sys.platform != "win32":
        return 96
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    modern = getattr(user32, "GetDpiForWindow", None)
    if modern is not None:
        modern.argtypes = [wintypes.HWND]
        modern.restype = wintypes.UINT
        dpi = modern(hwnd)
        if dpi > 0:
            return int(dpi)
    user32.GetDC.argtypes = [wintypes.HWND]
    user32.GetDC.restype = wintypes.HDC
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    user32.ReleaseDC.restype = ctypes.c_int
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    gdi32.GetDeviceCaps.argtypes = [wintypes.HDC, ctypes.c_int]
    gdi32.GetDeviceCaps.restype = ctypes.c_int
    dc = user32.GetDC(hwnd)
    if not dc:
        return 96
    try:
        dpi = gdi32.GetDeviceCaps(dc, 88)  # LOGPIXELSX
        return dpi if dpi > 0 else 96
    finally:
        user32.ReleaseDC(hwnd, dc)
