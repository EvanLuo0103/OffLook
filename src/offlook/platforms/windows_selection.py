"""Read one local file from the unique foreground Explorer or desktop view.

The synchronous provider belongs in a disposable selection worker, never a Tk
callback. Importing this module neither imports pywin32 nor initializes COM.
Only HWNDs are inspected for background windows; selections are read exclusively
from a visible active view rooted at the supplied foreground HWND.
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
from pathlib import Path
import sys
import traceback
from typing import TYPE_CHECKING, Any

from ..core.errors import FileAccessError

if TYPE_CHECKING:
    from ..core.config import PreviewConfig


@dataclass(frozen=True)
class SelectionRequest:
    """Pickle-safe selection request with its captured HWND and frozen config.

    ``request_id`` identifies the controller generation; ``config`` supplies the
    worker deadline. No COM interface crosses the process boundary.
    """

    request_id: int
    foreground_hwnd: int
    config: PreviewConfig
    for_search: bool = False


@dataclass(frozen=True)
class SelectionResult:
    """Return an optional local path and a human-readable no-selection reason.

    ``None`` is reserved for an unsupported foreground view or changed focus;
    empty/multiple/virtual selections are errors instead of successful results.
    """

    path: Path | None
    reason: str


class ExplorerSelectionProvider:
    """Query Shell selection synchronously in the calling process and STA.

    Use in a hard-timeout worker. This provider does not activate windows, guess
    desktop paths, resolve shortcuts, or read clipboard/background selections.
    """

    def get_selected_file(self, foreground_hwnd: int, *, for_search: bool = False) -> Path | None:
        """Return the sole selected local file/folder, or None for lost focus.

        Args:
            foreground_hwnd: Foreground top-level HWND captured at key receipt.
        Raises:
            FileAccessError: Invalid/ambiguous selection, unavailable pywin32,
                COM/apartment errors, or a file rejected by local validation.

        Native CoInitializeEx/CoUninitialize calls are deliberately paired here:
        pythoncom may initialize its first importing thread implicitly and may
        elide later CoInitializeEx calls on that thread. A native explicit pair
        owns exactly one reference without uninitializing pywin32's or a caller's
        pre-existing COM state. No COM objects outlive this explicit STA scope.
        """
        if sys.platform != "win32":
            raise FileAccessError("OffLook currently supports only Windows")
        if not isinstance(foreground_hwnd, int) or isinstance(foreground_hwnd, bool):
            raise FileAccessError("Invalid foreground window handle")
        if foreground_hwnd == 0:
            return None
        try:
            import win32gui
        except ImportError as exc:
            raise FileAccessError("Windows selection queries require pywin32") from exc
        if int(win32gui.GetForegroundWindow()) != foreground_hwnd:
            return None

        initialized = False
        ole32: Any = None
        try:
            # Import first: its implicit apartment reference belongs to pywin32,
            # not to the explicit native reference acquired below.
            import pythoncom

            ole32 = ctypes.WinDLL("ole32", use_last_error=True)
            ole32.CoInitializeEx.argtypes = (ctypes.c_void_p, ctypes.c_ulong)
            ole32.CoInitializeEx.restype = ctypes.c_long
            ole32.CoUninitialize.argtypes = ()
            ole32.CoUninitialize.restype = None
            result = ole32.CoInitializeEx(None, pythoncom.COINIT_APARTMENTTHREADED)
            if result < 0:
                raise FileAccessError(
                    f"Cannot initialize Windows selection queries in an STA (HRESULT 0x{result & 0xFFFFFFFF:08X})"
                )
            initialized = True
            try:
                path = _query_foreground(foreground_hwnd, pythoncom, win32gui)
            except Exception as exc:
                # dynamic.Dispatch frames may retain COM wrappers as ``self``.
                # Keep exception chains but release inactive frames before COM
                # uninitialization, including failures inside dispatch methods.
                _clear_exception_frames(exc)
                if int(win32gui.GetForegroundWindow()) != foreground_hwnd:
                    return None
                raise
            if int(win32gui.GetForegroundWindow()) != foreground_hwnd:
                return None
            return path
        except FileAccessError:
            raise
        except ImportError as exc:
            raise FileAccessError("Windows selection queries require a complete pywin32 installation") from exc
        except Exception as exc:
            raise FileAccessError(f"Cannot read the current file selection: {exc}"[:512]) from exc
        finally:
            if initialized:
                ole32.CoUninitialize()


def _active_view(dispatch: Any, pythoncom: Any, shell: Any) -> Any:
    """Return IShellBrowser's current active view, releasing intermediate COM refs.

    Args are a Shell dispatch and pywin32 modules; COM errors propagate to the
    provider boundary. Even exceptional tracebacks retain no input dispatch.
    """
    service_provider = browser = None
    try:
        service_provider = dispatch._oleobj_.QueryInterface(
            pythoncom.IID_IServiceProvider
        )
        browser = service_provider.QueryService(
            shell.SID_STopLevelBrowser, shell.IID_IShellBrowser
        )
        return browser.QueryActiveShellView()
    finally:
        browser = service_provider = dispatch = None


def _desktop_dispatch(windows: Any, pythoncom: Any, variant_type: Any) -> Any:
    """Return desktop IDispatch using the real five-argument FindWindowSW ABI.

    ``windows`` is IShellWindows; COM failures propagate, and all local COM
    references are dropped before returning/raising. No desktop directory is read.
    """
    desktop = result = None
    try:
        dispid = windows._oleobj_.GetIDsOfNames("FindWindowSW")
        result = windows._oleobj_.InvokeTypes(
            dispid,
            0,
            pythoncom.DISPATCH_METHOD,
            (pythoncom.VT_DISPATCH, 0),
            (
                (pythoncom.VT_VARIANT | pythoncom.VT_BYREF, pythoncom.PARAMFLAG_FIN),
                (pythoncom.VT_VARIANT | pythoncom.VT_BYREF, pythoncom.PARAMFLAG_FIN),
                (pythoncom.VT_I4, pythoncom.PARAMFLAG_FIN),
                (pythoncom.VT_I4 | pythoncom.VT_BYREF, pythoncom.PARAMFLAG_FOUT),
                (pythoncom.VT_I4, pythoncom.PARAMFLAG_FIN),
            ),
            variant_type(pythoncom.VT_I4, 0),
            variant_type(pythoncom.VT_EMPTY, None),
            8,
            None,
            1,
        )
        desktop, _desktop_hwnd = result
        return desktop
    finally:
        desktop = result = windows = None


def _query_foreground(foreground_hwnd: int, pythoncom: Any, gui: Any) -> Path | None:
    """Inspect candidate HWNDs, then read only a unique matching active view.

    Runs after STA initialization. Returns None for focus changes/unsupported
    views; raises FileAccessError for invalid selections and propagates COM errors.
    All COM locals are explicitly cleared before the caller uninitializes COM.
    """
    from win32com.client import VARIANT
    from win32com.client import dynamic
    from win32com.shell import shell, shellcon

    application = windows = window = view = desktop = None
    background = folder_view = selected = item = None
    candidates: dict[int, Any] = {}
    try:
        if int(gui.GetForegroundWindow()) != foreground_hwnd:
            return None
        application = dynamic.Dispatch("Shell.Application")
        windows = application.Windows()
        # Do not enumerate SelectedItems, paths, or locations of other windows.
        for index in range(int(windows.Count)):
            window = windows.Item(index)
            if window is None or int(window.HWND) != foreground_hwnd:
                window = None
                continue
            view = _active_view(window, pythoncom, shell)
            view_hwnd = int(view.GetWindow())
            if gui.IsWindowVisible(view_hwnd) and (
                int(gui.GetAncestor(view_hwnd, 2)) == foreground_hwnd
            ):
                candidates[view_hwnd] = view
            view = window = None
        if int(gui.GetForegroundWindow()) != foreground_hwnd:
            return None
        if not candidates:
            desktop = _desktop_dispatch(windows, pythoncom, VARIANT)
            if desktop is not None:
                desktop = dynamic.Dispatch(desktop)
                view = _active_view(desktop, pythoncom, shell)
                view_hwnd = int(view.GetWindow())
                if gui.IsWindowVisible(view_hwnd) and (
                    int(gui.GetAncestor(view_hwnd, 2)) == foreground_hwnd
                ):
                    candidates[view_hwnd] = view
                view = desktop = None
        if int(gui.GetForegroundWindow()) != foreground_hwnd:
            return None
        if not candidates:
            return None
        if len(candidates) != 1:
            raise FileAccessError("Cannot uniquely identify the current file view")
        view = next(iter(candidates.values()))
        background = view.GetItemObject(
            shellcon.SVGIO_BACKGROUND, pythoncom.IID_IDispatch
        )
        folder_view = dynamic.Dispatch(background)
        if int(gui.GetForegroundWindow()) != foreground_hwnd:
            return None
        selected = folder_view.SelectedItems()
        count = int(selected.Count)
        if count == 0:
            raise FileAccessError("No file is selected; select one local file")
        if count != 1:
            raise FileAccessError("Multiple items are selected; select only one local file")
        item = selected.Item(0)
        if not bool(item.IsFileSystem):
            raise FileAccessError("The selected item is not a local file system file")
        if bool(item.IsFolder) and not for_search:
            raise FileAccessError("Folder previews are not supported; select one local file")
        if for_search and not bool(item.IsFolder):
            raise FileAccessError("Select a folder in File Explorer to start a folder search")
        path = item.Path
        if not isinstance(path, str) or not path:
            raise FileAccessError("The selected item has no valid local file path")
        if int(gui.GetForegroundWindow()) != foreground_hwnd:
            return None
        from .windows_files import validate_local_file
        if for_search:
            folder = Path(path)
            try:
                if not folder.is_dir():
                    raise FileAccessError("Select a folder in File Explorer to start a folder search")
            except OSError as exc:
                raise FileAccessError("The selected folder cannot be accessed") from exc
            return folder
        return validate_local_file(path)
    finally:
        item = selected = folder_view = background = None
        view = desktop = window = None
        candidates.clear()
        windows = application = None


def _clear_exception_frames(error: BaseException) -> None:
    """Release inactive COM-bearing frames while retaining an exception chain.

    Args:
        error: Dispatch failure whose causes/contexts may also retain wrappers.
    Returns:
        None; exception types, messages, links, and traceback locations survive.
    """
    pending = [error]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        traceback.clear_frames(current.__traceback__)
        if current.__cause__ is not None:
            pending.append(current.__cause__)
        if current.__context__ is not None:
            pending.append(current.__context__)
