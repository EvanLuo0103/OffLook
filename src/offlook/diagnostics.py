"""Interactive Windows diagnostics for global shortcuts and Explorer selection."""

from __future__ import annotations

import time

from offlook.core.errors import FileAccessError
from offlook.platforms.windows_hotkey import HotkeyListener
from offlook.platforms.windows_selection import ExplorerSelectionProvider


def run_search_shortcut_diagnostic(combo: str) -> int:
    """Test the configured key and local Explorer folder selection without a GUI."""
    listener = HotkeyListener(combo)
    listener.start()
    provider = ExplorerSelectionProvider()
    print(f"OffLook {listener.combo} diagnostic is running.")
    print(f"Select one local folder, or open it with nothing selected, in File Explorer; then press {listener.combo}.")
    print("Press Ctrl+C to stop.")
    try:
        while True:
            for event in listener.poll():
                if event["type"] == "ready":
                    print(f"PASS: OffLook registered {listener.combo}.")
                elif event["type"] == "error":
                    print(f"FAIL: OffLook could not register {listener.combo}: {event['message']}")
                    return 2
                elif event["type"] == "hotkey":
                    print(f"PASS: OffLook detected {event.get('combo', listener.combo)}.")
                    try:
                        path = provider.get_selected_file(
                            event["foreground_hwnd"], allow_folder=True
                        )
                    except FileAccessError as exc:
                        print(f"FAIL: Explorer selection check failed: {exc}")
                    else:
                        if path is None:
                            print("FAIL: File Explorer focus changed before it could be checked.")
                        elif path.is_dir():
                            print(f"PASS: Selected local folder confirmed: {path}")
                        else:
                            print(f"FAIL: Selected item is not a folder: {path}")
            time.sleep(0.05)
    except KeyboardInterrupt:
        print("\nDiagnostic stopped.")
        return 0
    finally:
        listener.stop()
