"""Built-in English help window; no browser or external markdown reader."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from offlook.ui.theme import COLORS, window_fonts, size_window


_HELP_TEXT = """Choosing a file to preview
Click "Choose file" in the main window, or run:
  offlook preview ".\\README.md"
Select one file in File Explorer or on the desktop, then press the current shortcut to preview it.

Searching files
In "Search files", choose a local folder and optionally enter part of a filename. Choose "All types", a content category, "Documents (.doc/.xlsx)", or "Other / unknown", then click "Search".
The search includes subfolders but does not follow links or network folders. Double-click a result to preview it.
Office and OpenDocument files are identified for searching, but OffLook shows their metadata instead of parsing their contents.

Current shortcut
{hotkey}
Esc or unmodified Space closes the preview; Space with Ctrl, Alt, or Shift does not.
You can still choose files in the main window when the global shortcut is disabled.
The fixed Ctrl+Alt+F Search shortcut is separate from the preview shortcut. In File Explorer, select one local folder and press it to open Search files at that folder; selecting a file shows an explanatory error.

Preview controls
PDFs have Previous / Next buttons; page numbers appear only for rendered PDF pages. "Always on top" applies only to the current preview.
When you enlarge the window or move it to a higher-DPI display, images and PDFs are rendered again with more physical pixels, rather than repeatedly enlarging the old image.

Shortcut settings and conflicts
Click "Record shortcut", press a combination inside OffLook, then click "Apply". Recording does not activate it; if registration fails, the previous shortcut remains active.
Win-key combinations, F12, single keys, and reserved combinations such as Alt+F4 are not supported. If another app uses the combination, choose another with Ctrl or Alt.

Add to PATH
"Add to PATH" in the main window updates only the current user's environment. It does not change the system PATH or other versions. Reopen PowerShell afterward; restart Windows Terminal if needed.
Existing terminals may still use the old environment. You can also run `py -m offlook`.

System tray, startup, and exit
Closing the main window hides it to the system tray, where you can restore it or exit. Start at sign-in must be explicitly enabled in the main window. Exiting stops background listening and pending work.

File limits and offline operation
OffLook reads only local files. It makes no network connections, executes no file content, and uses no Windows or third-party thumbnail providers.
Safety limits apply to file size, text length, image pixels, and preview time. Unknown formats, files over these limits, and empty files show a file information card, not a hex dump.
Content previews support images, PDFs, text, Markdown, code, and CSV. Word, Excel, PowerPoint, OpenDocument, unknown, and unsupported files show the information card with the full path, file attributes, and human-readable size.
"""


def show_help(parent: tk.Misc, *, hotkey: str) -> tk.Toplevel:
    """Create and return one scrollable, read-only help Toplevel."""
    window = tk.Toplevel(parent)
    window._offlook_font_prefix = "Help"
    window.title("OffLook Help")
    window.transient(parent)
    try:
        dpi = 96
        from offlook.platforms.windows_dpi import window_dpi
        dpi = window_dpi(window.winfo_id())
    except (ImportError, OSError, tk.TclError):
        dpi = 96
    fonts = window_fonts(window, dpi)
    size_window(window, dpi, 700, 650, 500, 380, monitor=parent)
    window.configure(background=COLORS["background"])
    header = ttk.Frame(window, style="Card.TFrame", padding=(24, 18, 24, 10))
    header.pack(fill="x", padx=16, pady=(16, 0))
    ttk.Label(header, text="Help", style="Help.Title.TLabel").pack(anchor="w")
    ttk.Label(header, text="Offline file previews and system integration", style="Card.Muted.TLabel").pack(anchor="w", pady=(4, 0))
    frame = ttk.Frame(window, style="Card.TFrame", padding=(24, 12, 12, 16))
    frame.pack(fill="both", expand=True, padx=16, pady=(0, 16))
    text = tk.Text(frame, wrap="word", relief="flat", borderwidth=0,
                   background=COLORS["card"], foreground=COLORS["text"],
                   insertbackground=COLORS["text"], padx=4, pady=4,
                   font=fonts["body"], spacing1=2, spacing3=6)
    scroll = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
    text.configure(yscrollcommand=scroll.set)
    text.grid(row=0, column=0, sticky="nsew")
    scroll.grid(row=0, column=1, sticky="ns")
    frame.rowconfigure(0, weight=1)
    frame.columnconfigure(0, weight=1)
    content = _HELP_TEXT.format(hotkey=hotkey if hotkey else "Disabled")
    text.insert("1.0", content)
    text.configure(state="disabled", cursor="arrow")
    window.bind("<Escape>", lambda _event: window.destroy())
    window.protocol("WM_DELETE_WINDOW", window.destroy)
    window.focus_set()
    return window
