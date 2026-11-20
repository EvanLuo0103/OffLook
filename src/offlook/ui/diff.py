"""Tk presentation for a Git working-tree versus HEAD comparison."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from dataclasses import dataclass

from offlook.core.git_diff import FileComparison, GitComparison
from offlook.ui.i18n import tr
from offlook.ui.theme import COLORS, size_window, window_fonts
from offlook.platforms.windows_dpi import window_dpi


@dataclass(frozen=True)
class SideBySideRow:
    """One aligned row in the side-by-side comparison view."""

    left_text: str = ""
    left_line: int | None = None
    left_kind: str = "context"
    right_text: str = ""
    right_line: int | None = None
    right_kind: str = "context"


def side_by_side_rows(comparison: FileComparison | GitComparison) -> tuple[SideBySideRow, ...]:
    """Align classified diff lines into one left/right row per displayed change."""
    lines = comparison.lines
    rows: list[SideBySideRow] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.kind == "context":
            rows.append(SideBySideRow(
                line.text, line.old_line, "context",
                line.text, line.new_line, "context",
            ))
            index += 1
        elif line.kind == "modified-delete":
            right = lines[index + 1] if index + 1 < len(lines) else None
            if right is not None and right.kind == "modified-add":
                rows.append(SideBySideRow(
                    line.text, line.old_line, "modified-delete",
                    right.text, right.new_line, "modified-add",
                ))
                index += 2
            else:
                rows.append(SideBySideRow(
                    line.text, line.old_line, "modified-delete",
                ))
                index += 1
        elif line.kind == "deleted":
            deleted: list = [line]
            index += 1
            while index < len(lines) and lines[index].kind == "deleted":
                deleted.append(lines[index])
                index += 1
            added: list = []
            while index < len(lines) and lines[index].kind == "added":
                added.append(lines[index])
                index += 1
            row_count = max(len(deleted), len(added))
            for row_index in range(row_count):
                left = deleted[row_index] if row_index < len(deleted) else None
                right = added[row_index] if row_index < len(added) else None
                rows.append(SideBySideRow(
                    left.text if left else "",
                    left.old_line if left else None,
                    "deleted" if left else "context",
                    right.text if right else "",
                    right.new_line if right else None,
                    "added" if right else "context",
                ))
        elif line.kind == "added":
            rows.append(SideBySideRow(
                right_text=line.text,
                right_line=line.new_line,
                right_kind="added",
            ))
            index += 1
        else:
            index += 1
    return tuple(rows)


def show_diff(parent: tk.Misc, comparison: FileComparison | GitComparison) -> tk.Toplevel:
    """Create a synchronized, read-only side-by-side comparison window."""
    window = tk.Toplevel(parent)
    window._offlook_font_prefix = "Diff"
    if isinstance(comparison, FileComparison):
        old_name = comparison.old_path.name
        new_name = comparison.new_path.name
        title_name = f"{old_name} / {new_name}"
        heading_name = f"{old_name} -> {new_name}"
        status_path = f"{comparison.old_path}  |  {comparison.new_path}"
    else:
        title_name = comparison.path.name
        heading_name = f"{comparison.path.name} - working tree vs HEAD"
        status_path = str(comparison.repository)
    window.title(tr("diff.title", name=title_name))
    window.transient(parent)
    dpi = window_dpi(window.winfo_id())
    fonts = window_fonts(window, dpi)
    size_window(window, dpi, 1100, 760, 700, 420, monitor=parent)
    window.configure(background=COLORS["background"])
    heading = ttk.Frame(window, style="Card.TFrame", padding=16)
    heading.pack(fill="x", padx=16, pady=(16, 8))
    ttk.Label(heading, text=tr("diff.heading", name=heading_name),
              style="Diff.Title.TLabel").pack(anchor="w")
    status = tr("diff.empty") if not comparison.changed else tr("diff.legend")
    ttk.Label(heading, text=f"{status_path} · {status}",
              style="Diff.Card.Muted.TLabel").pack(anchor="w", pady=(4, 0))
    frame = ttk.Frame(window, style="Card.TFrame", padding=12)
    frame.pack(fill="both", expand=True, padx=16, pady=(0, 16))
    left_label = comparison.old_path.name if isinstance(comparison, FileComparison) else "HEAD"
    right_label = comparison.new_path.name if isinstance(comparison, FileComparison) else comparison.path.name
    ttk.Label(frame, text=left_label, style="Diff.Title.TLabel").grid(
        row=0, column=0, sticky="w", pady=(0, 6)
    )
    ttk.Label(frame, text=right_label, style="Diff.Title.TLabel").grid(
        row=0, column=2, sticky="w", pady=(0, 6)
    )
    left = tk.Text(frame, wrap="none", state="disabled", undo=False,
                   background=COLORS["card"], foreground=COLORS["text"],
                   font=fonts["code"], padx=8, pady=8)
    right = tk.Text(frame, wrap="none", state="disabled", undo=False,
                    background=COLORS["card"], foreground=COLORS["text"],
                    font=fonts["code"], padx=8, pady=8)

    scroll_y = ttk.Scrollbar(frame, orient="vertical")
    scroll_x_left = ttk.Scrollbar(frame, orient="horizontal", command=left.xview)
    scroll_x_right = ttk.Scrollbar(frame, orient="horizontal", command=right.xview)
    left.configure(xscrollcommand=scroll_x_left.set)
    right.configure(xscrollcommand=scroll_x_right.set)

    def scroll_both(*args):
        left.yview(*args)
        right.yview(*args)

    scroll_y.configure(command=scroll_both)
    def sync_left(first, last):
        scroll_y.set(first, last)
        right.yview_moveto(first)

    left.configure(yscrollcommand=sync_left)
    right.configure(yscrollcommand=lambda first, last: scroll_y.set(first, last))

    left.grid(row=1, column=0, sticky="nsew")
    ttk.Separator(frame, orient="vertical").grid(row=1, column=1, sticky="ns", padx=6)
    right.grid(row=1, column=2, sticky="nsew")
    scroll_y.grid(row=1, column=3, sticky="ns")
    scroll_x_left.grid(row=2, column=0, sticky="ew")
    scroll_x_right.grid(row=2, column=2, sticky="ew")
    frame.rowconfigure(1, weight=1)
    frame.columnconfigure(0, weight=1)
    frame.columnconfigure(2, weight=1)
    for tag, color in (
        ("added", "#E8F5E9"), ("deleted", "#FDECEC"),
        ("modified-delete", "#FFF4E5"), ("modified-add", "#FFF4E5"),
    ):
        left.tag_configure(tag, background=color)
        right.tag_configure(tag, background=color)
    left.configure(state="normal")
    right.configure(state="normal")
    for row in side_by_side_rows(comparison):
        old = "-" if row.left_line is None else str(row.left_line)
        new = "-" if row.right_line is None else str(row.right_line)
        left.insert("end", f"{old:>6}  {row.left_text}\n", row.left_kind)
        right.insert("end", f"{new:>6}  {row.right_text}\n", row.right_kind)
    left.configure(state="disabled")
    right.configure(state="disabled")
    window.bind("<Escape>", lambda _event: window.destroy())
    window.protocol("WM_DELETE_WINDOW", window.destroy)
    window.focus_set()
    return window
