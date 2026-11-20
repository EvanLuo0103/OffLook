"""Launch helpers for the onedir Windows distribution."""
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import sys
from threading import Lock

from offlook.core.errors import OffLookError

frozen_spawn_lock = Lock()


def frozen_gui_executable() -> Path | None:
    if not getattr(sys, 'frozen', False):
        return None
    executable = Path(sys.executable).absolute().with_name('OffLook.exe')
    if not executable.is_file():
        raise OffLookError('OffLook.exe is missing; reinstall OffLook')
    return executable


@contextmanager
def external_process_environment():
    """Yield a sanitized child environment only during external process creation."""
    bundle = Path(sys._MEIPASS).resolve()
    environment = os.environ.copy()
    if 'PATH' in environment:
        def outside(entry: str) -> bool:
            return not entry or not Path(entry.strip('"')).resolve().is_relative_to(bundle)

        environment['PATH'] = os.pathsep.join(e for e in environment['PATH'].split(os.pathsep) if outside(e))
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    get_dir = kernel32.GetDllDirectoryW
    get_dir.argtypes = (wintypes.DWORD, wintypes.LPWSTR)
    get_dir.restype = wintypes.DWORD
    set_dir = kernel32.SetDllDirectoryW
    set_dir.argtypes = (wintypes.LPCWSTR,)
    set_dir.restype = wintypes.BOOL
    with frozen_spawn_lock:
        buffer = ctypes.create_unicode_buffer(32768)
        ctypes.set_last_error(0)
        length = get_dir(len(buffer), buffer)
        if length >= len(buffer) or (not length and ctypes.get_last_error()):
            raise OSError('Cannot read the bundled DLL search directory')
        if not set_dir(None):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            yield environment
        finally:
            if not set_dir(buffer.value if length else None):
                raise ctypes.WinError(ctypes.get_last_error())
