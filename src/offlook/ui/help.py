"""Built-in English help window; no browser or external markdown reader."""
from __future__ import annotations

from collections.abc import Mapping
import tkinter as tk
from tkinter import ttk

from offlook.ui.theme import COLORS, window_fonts, size_window


_HELP_TEXT = """Choosing a file to preview
Click "Choose file" in the main window, or run:
  offlook preview ".\\README.md"
Select one file in File Explorer or on the desktop, then press the configured Preview shortcut. Its default is Ctrl+Space.

Searching files
In "Search files", choose a local folder and optionally enter part of a filename. Choose "All types", a content category, "Documents (.doc/.xlsx)", or "Other / unknown", then click "Search".
The search includes subfolders but does not follow links or network folders. Double-click a result to preview it.
In File Explorer, select one local folder, or open a local folder with nothing selected, then press the configured Search files shortcut (default: Ctrl+Q). OffLook loads the folder and focuses the filename field; it does not run a search until you click "Search". A selected regular file or multiple items is an error, not a request to search the parent folder.

Git comparison
The separate "Git comparison" card contains "Compare with Git HEAD". Select a tracked text file there, or select it in File Explorer and press the configured Git comparison shortcut (default: Ctrl+Alt+D). The window compares the working file with HEAD line by line and highlights added, deleted, and modified lines.
Office and OpenDocument files are identified for searching, but OffLook shows their metadata instead of parsing their contents.

Current global shortcuts
Preview: {preview}
Search files: {search}
Git comparison: {diff}
This summary updates when shortcut registration changes. An active key can differ from the configured key if a replacement fails.
Esc or unmodified Space closes the preview; Space with Ctrl, Alt, or Shift does not.
You can still choose files, search, and compare manually when global shortcuts are disabled or unavailable.

Preview controls
PDFs have Previous / Next buttons; page numbers appear only for rendered PDF pages. "Always on top" applies only to the current preview.
When you enlarge the window or move it to a higher-DPI display, images and PDFs are rendered again with more physical pixels, rather than repeatedly enlarging the old image.

Shortcut settings and conflicts
Choose Preview, Search files, or Git comparison in the action selector. Each action keeps its own draft. Click "Record shortcut", press a combination inside OffLook, then click "Apply" to save only the selected action. Esc cancels recording; switching actions cancels unfinished recording. "Reset default" changes only the selected draft and also requires Apply.
"Enable global shortcuts" applies immediately to all three actions, independently of Apply. Disabling releases all keys; enabling attempts each saved key independently. A key that another application owns is shown as Unavailable, while the other actions can still work.
Combinations must be different for all three actions, even while disabled. If registration or saving fails, the previous active key remains; the proposed draft is kept for correction or retry. Release an occupied key in the other application, then Apply again, or choose another combination. Changing externally configured keys does not implicitly swap active registrations: use an intermediate unused key to release the old one.
Recording does not activate a shortcut or execute a feature, including when you press an already-registered Search files or Git comparison key over OffLook's main window.
Win-key combinations, F12, single keys, and reserved combinations such as Alt+F4 are not supported. Choose a combination with Ctrl or Alt, optionally Shift.

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


def show_help(parent: tk.Misc, *, shortcuts: Mapping[str, str]) -> tk.Toplevel:
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
    window._offlook_help_text = text
    text.configure(cursor="arrow")
    update_help_shortcuts(window, shortcuts=shortcuts)
    window.bind("<Escape>", lambda _event: window.destroy())
    window.protocol("WM_DELETE_WINDOW", window.destroy)
    window.focus_set()
    return window


def update_help_shortcuts(window: tk.Toplevel, *, shortcuts: Mapping[str, str]) -> None:
    """Refresh the existing Help body without changing focus or scroll position."""
    text = window._offlook_help_text
    position = text.yview()[0]
    content = _HELP_TEXT.format(
        preview=shortcuts["preview"],
        search=shortcuts["search"],
        diff=shortcuts["diff"],
    )
    text.configure(state="normal")
    text.delete("1.0", "end")
    text.insert("1.0", content)
    text.configure(state="disabled")
    text.yview_moveto(position)
