"""Tk presentation for a Git working-tree versus HEAD comparison."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from offlook.core.git_diff import GitComparison
from offlook.ui.theme import COLORS, size_window, window_fonts
from offlook.platforms.windows_dpi import window_dpi


def show_diff(parent: tk.Misc, comparison: GitComparison) -> tk.Toplevel:
    """Create a read-only, color-highlighted line comparison window."""
    window = tk.Toplevel(parent)
    window._offlook_font_prefix = "Diff"
    window.title(f"Git comparison — {comparison.path.name}")
    window.transient(parent)
    dpi = window_dpi(window.winfo_id())
    fonts = window_fonts(window, dpi)
    size_window(window, dpi, 1100, 760, 700, 420, monitor=parent)
    window.configure(background=COLORS["background"])
    heading = ttk.Frame(window, style="Card.TFrame", padding=16)
    heading.pack(fill="x", padx=16, pady=(16, 8))
    ttk.Label(heading, text=f"{comparison.path.name} — working tree vs HEAD",
              style="Diff.Title.TLabel").pack(anchor="w")
    status = "No line differences." if not comparison.changed else "Added green · deleted red · modified amber"
    ttk.Label(heading, text=f"{comparison.repository} · {status}",
              style="Diff.Card.Muted.TLabel").pack(anchor="w", pady=(4, 0))
    frame = ttk.Frame(window, style="Card.TFrame", padding=12)
    frame.pack(fill="both", expand=True, padx=16, pady=(0, 16))
    text = tk.Text(frame, wrap="none", state="disabled", undo=False,
                   background=COLORS["card"], foreground=COLORS["text"],
                   font=fonts["code"], padx=8, pady=8)
    scroll_y = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
    scroll_x = ttk.Scrollbar(frame, orient="horizontal", command=text.xview)
    text.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)
    text.grid(row=0, column=0, sticky="nsew")
    scroll_y.grid(row=0, column=1, sticky="ns")
    scroll_x.grid(row=1, column=0, sticky="ew")
    frame.rowconfigure(0, weight=1)
    frame.columnconfigure(0, weight=1)
    for tag, color in (
        ("added", "#E8F5E9"), ("deleted", "#FDECEC"),
        ("modified-delete", "#FFF4E5"), ("modified-add", "#FFF4E5"),
    ):
        text.tag_configure(tag, background=color)
    text.configure(state="normal")
    for line in comparison.lines:
        old = "-" if line.old_line is None else str(line.old_line)
        new = "-" if line.new_line is None else str(line.new_line)
        text.insert("end", f"{old:>6} {new:>6}  {line.kind[:1].upper()} {line.text}\n", line.kind)
    text.configure(state="disabled")
    window.bind("<Escape>", lambda _event: window.destroy())
    window.protocol("WM_DELETE_WINDOW", window.destroy)
    window.focus_set()
    return window
