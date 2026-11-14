"""Interactive Windows diagnostics for global shortcuts and Explorer selection."""

from __future__ import annotations

import time

from offlook.core.errors import FileAccessError
from offlook.platforms.windows_hotkey import HotkeyListener
from offlook.platforms.windows_selection import ExplorerSelectionProvider


def run_search_shortcut_diagnostic() -> int:
    """Wait for Ctrl+Q and report whether one local Explorer folder is selected."""
    listener = HotkeyListener("Ctrl+Q")
    listener.start()
    provider = ExplorerSelectionProvider()
    print("OffLook Ctrl+Q diagnostic is running.")
    print("Select exactly one local folder in File Explorer, then press Ctrl+Q.")
    print("Press Ctrl+C to stop.")
    try:
        while True:
            for event in listener.poll():
                if event["type"] == "ready":
                    print("PASS: OffLook registered Ctrl+Q.")
                elif event["type"] == "error":
                    print(f"FAIL: OffLook could not register Ctrl+Q: {event['message']}")
                    return 2
                elif event["type"] == "hotkey":
                    print("PASS: OffLook detected Ctrl+Q.")
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
