"""Shared search and filter result table for Tk views."""
from __future__ import annotations

from collections.abc import Callable, Iterable
import tkinter as tk
from tkinter import ttk

from offlook.core.files import FileKind
from offlook.core.search import SearchResult
from offlook.ui.i18n import kind_label, tr


def build_result_table(parent: tk.Misc, on_open: Callable[[tk.Event], object], *,
                       scale: float, style: str = 'Main.Treeview',
                       text: Callable[[str], str] = tr, expand: bool = False) -> ttk.Treeview:
    frame = ttk.Frame(parent)
    frame.pack(fill='both' if expand else 'x', expand=expand)
    frame.columnconfigure(0, weight=1)
    if expand:
        frame.rowconfigure(0, weight=1)
    tree = ttk.Treeview(frame, columns=('type', 'path'), show='headings', height=8, style=style)
    tree.heading('type', text=text('col.type'))
    tree.heading('path', text=text('col.path'))
    tree.column('type', width=round(96 * scale), stretch=False)
    tree.column('path', width=round(380 * scale), minwidth=round(240 * scale))
    tree.grid(row=0, column=0, sticky='nsew' if expand else 'ew')
    vertical = ttk.Scrollbar(frame, orient='vertical', command=tree.yview)
    horizontal = ttk.Scrollbar(frame, orient='horizontal', command=tree.xview)
    vertical.grid(row=0, column=1, sticky='ns')
    horizontal.grid(row=1, column=0, sticky='ew')
    tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
    tree.bind('<Double-1>', on_open)
    return tree


def fill_results(tree: ttk.Treeview, rows: Iterable[SearchResult], *,
                 label_kind: Callable[[FileKind], str] = kind_label) -> None:
    tree.delete(*tree.get_children())
    for row in rows:
        tree.insert('', 'end', values=(label_kind(row.kind), str(row.path)))
