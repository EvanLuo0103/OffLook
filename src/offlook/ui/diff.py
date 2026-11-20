"""Tk presentation for local file comparisons."""

from __future__ import annotations

from collections.abc import Callable
from itertools import groupby
import tkinter as tk
from tkinter import ttk

from dataclasses import dataclass

from offlook.core.file_comparison import DiffLine, FileComparison
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
    left_emphasis: tuple[tuple[int, int], ...] = ()
    right_emphasis: tuple[tuple[int, int], ...] = ()
    left_no_newline: bool = False
    right_no_newline: bool = False


def _split_rows(lines: tuple[DiffLine, ...]) -> tuple[SideBySideRow, ...]:
    def pair(left: DiffLine | None, right: DiffLine | None) -> SideBySideRow:
        return SideBySideRow(
            left.text if left else '', left.old_line if left else None, left.kind if left else 'context',
            right.text if right else '', right.new_line if right else None, right.kind if right else 'context',
            left.emphasis if left else (), right.emphasis if right else (),
            bool(left and left.no_newline), bool(right and right.no_newline),
        )

    rows = []
    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1
        if line.kind == 'context':
            rows.append(pair(line, line))
        elif line.kind == 'modified-delete' and i < len(lines) and lines[i].kind == 'modified-add':
            rows.append(pair(line, lines[i]))
            i += 1
        elif line.old_line is not None:
            rows.append(pair(line, None))
        else:
            rows.append(pair(None, line))
    return tuple(rows)


def side_by_side_rows(comparison: FileComparison) -> tuple[SideBySideRow, ...]:
    """Align paired modifications and context without inventing source lines."""
    return _split_rows(comparison.lines)


def _unified_rows(lines: tuple[DiffLine, ...]):
    for is_context, group in groupby(lines, key=lambda line: line.kind == 'context'):
        if is_context:
            yield from group
        else:
            changed = list(group)
            yield from (line for line in changed if line.old_line is not None)
            yield from (line for line in changed if line.new_line is not None)


@dataclass(frozen=True)
class _Hunk:
    start: int
    stop: int
    header: str


def _hunks(lines: tuple[DiffLine, ...]) -> tuple[_Hunk, ...]:
    ranges: list[tuple[int, int]] = []
    old, new = [0], [0]
    for i, line in enumerate(lines):
        old.append(old[-1] + (line.old_line is not None))
        new.append(new[-1] + (line.new_line is not None))
        if line.kind == 'context':
            continue
        start, stop = max(0, i - 3), min(len(lines), i + 4)
        if ranges and start <= ranges[-1][1]:
            ranges[-1] = ranges[-1][0], stop
        else:
            ranges.append((start, stop))
    hunks = []
    for start, stop in ranges:
        oc, nc = old[stop] - old[start], new[stop] - new[start]
        os, ns = old[start] + bool(oc), new[start] + bool(nc)
        hunks.append(_Hunk(start, stop, f'@@ -{os},{oc} +{ns},{nc} @@'))
    return tuple(hunks)


def _paint_line(widget: tk.Text, numbers: tuple[int | None, ...], kind: str, text: str,
                emphasis: tuple[tuple[int, int], ...]) -> None:
    color, mark = ('removed', '-') if kind in ('deleted', 'modified-delete') else (
        ('added', '+') if kind in ('added', 'modified-add') else ('context', ' '))
    gutter = ''.join(f'{number if number is not None else "":>6} ' for number in numbers) + f'{mark} '
    widget.insert('end', gutter, (color, 'gutter'))
    # Insert segments directly so Tk computes character indices across Unicode itself.
    cursor = 0
    for start, stop in emphasis:
        widget.insert('end', text[cursor:start], (color,))
        widget.insert('end', text[start:stop], (color, f'{color}-inline'))
        cursor = stop
    widget.insert('end', text[cursor:] + '\n', (color,))


def show_diff(parent: tk.Misc, comparison: FileComparison, *,
              on_swap: Callable[[], None] | None = None) -> tk.Toplevel:
    """Display a read-only comparison in Split or Unified mode."""
    window = tk.Toplevel(parent)
    window._offlook_font_prefix = 'Diff'
    old, new = comparison.old_path, comparison.new_path
    window.title(tr('diff.title', name=f'{old.name} / {new.name}'))
    if parent.winfo_viewable():
        window.transient(parent)
    dpi = window_dpi(window.winfo_id())
    fonts = window_fonts(window, dpi)
    size_window(window, dpi, 1100, 760, 700, 420, monitor=parent)
    window.configure(background=COLORS['background'])
    heading = ttk.Frame(window, style='Card.TFrame', padding=12)
    heading.pack(fill='x', padx=16, pady=(16, 8))
    ttk.Label(heading, text=tr('diff.heading', name=f'{old.name} → {new.name}'),
              style='Diff.Title.TLabel').pack(anchor='w')
    for key, path in (('old', old), ('new', new)):
        ttk.Label(heading, text=f'{tr(f"compare_picker.{key}")}: {path}',
                  style='Diff.Card.Muted.TLabel', wraplength=round(640 * dpi / 96)).pack(anchor='w')
    toolbar = ttk.Frame(heading, style='Card.TFrame')
    toolbar.pack(fill='x', pady=(6, 0))
    lines = comparison.lines
    hunks = _hunks(lines)
    added = sum(line.kind in ('added', 'modified-add') for line in lines)
    deleted = sum(line.kind in ('deleted', 'modified-delete') for line in lines)
    ttk.Label(toolbar, text=f'+{added}', foreground='#1a7f37', style='Diff.Card.TLabel').pack(side='left')
    ttk.Label(toolbar, text=f'−{deleted}', foreground='#cf222e', style='Diff.Card.TLabel').pack(side='left', padx=6)
    ttk.Label(toolbar, text=tr('diff.counts', added=added, deleted=deleted),
              style='Diff.Card.Muted.TLabel').pack(side='left', padx=6)
    if on_swap is not None:
        ttk.Button(toolbar, text=tr('diff.swap'), command=on_swap).pack(side='right')
    mode = tk.StringVar(window, value='split')
    expanded: set[tuple[int, int]] = set()
    body = ttk.Frame(window, style='Card.TFrame', padding=8)
    body.pack(fill='both', expand=True, padx=16, pady=(0, 16))
    panes: list[tk.Text] = []
    display_rows: list[tuple[int | None, int | None]] = []

    def render(*, gap: tuple[int, int] | None = None, anchor=(None, None)) -> None:
        for child in body.winfo_children():
            child.destroy()
        panes.clear()
        display_rows.clear()
        if not hunks:
            ttk.Label(body, text=tr('diff.empty'), style='Diff.Card.TLabel').pack(anchor='w')
            return

        split = mode.get() == 'split'
        grid = ttk.Frame(body, style='Card.TFrame')
        grid.pack(fill='both', expand=True)
        grid.rowconfigure(1, weight=1)
        view_scroll = ttk.Scrollbar(grid, orient='vertical')
        view_scroll.grid(row=1, column=2 if split else 1, sticky='ns')

        for column, title in enumerate((old.name, new.name) if split else (f'{old.name} → {new.name}',)):
            grid.columnconfigure(column, weight=1, uniform='diff')
            ttk.Label(grid, text=title, style='Diff.Section.TLabel').grid(row=0, column=column, sticky='w', pady=(0, 4))
            pane = tk.Text(grid, wrap='none', undo=False, width=1, borderwidth=1, relief='solid',
                           background=COLORS['card'], foreground=COLORS['text'], font=fonts['code'])
            panes.append(pane)
            scroll = ttk.Scrollbar(grid, orient='horizontal', command=pane.xview)
            pane.configure(xscrollcommand=scroll.set)
            pane.grid(row=1, column=column, sticky='nsew')
            scroll.grid(row=2, column=column, sticky='ew')
            for name, color in (('added', '#e6ffec'), ('removed', '#ffebe9'), ('hunk', '#ddf4ff')):
                pane.tag_configure(name, background=color)
            pane.tag_configure('gutter', foreground='#57606a')
            pane.tag_configure('note', foreground='#57606a')
            pane.tag_configure('added-inline', background='#abf2bc')
            pane.tag_configure('removed-inline', background='#ffcccd')
            pane.tag_raise('sel')

        target = 1
        found = False

        def record(old_line=None, new_line=None):
            nonlocal target, found
            display_rows.append((old_line, new_line))
            if not found and gap is None and any(a is not None and a == b for a, b in zip(anchor, display_rows[-1])):
                target, found = len(display_rows), True

        def banner(text, tag='hunk', extra=()):
            for pane in panes:
                pane.insert('end', f'  {text}\n', (tag, *extra))
            record()

        def rows(start, stop):
            selection = lines[start:stop]
            note = tr('diff.no_newline')
            if split:
                left, right = panes
                for row in _split_rows(selection):
                    _paint_line(left, (row.left_line,), row.left_kind, row.left_text, row.left_emphasis)
                    _paint_line(right, (row.right_line,), row.right_kind, row.right_text, row.right_emphasis)
                    record(row.left_line, row.right_line)
                    if row.left_no_newline or row.right_no_newline:
                        left.insert('end', (note if row.left_no_newline else '') + '\n', ('note',))
                        right.insert('end', (note if row.right_no_newline else '') + '\n', ('note',))
                        record()
            else:
                for line in _unified_rows(selection):
                    _paint_line(panes[0], (line.old_line, line.new_line), line.kind, line.text, line.emphasis)
                    record(line.old_line, line.new_line)
                    if line.no_newline:
                        banner(note, 'note')

        def expand(key):
            expanded.add(key)
            render(gap=key)

        def unchanged(start, stop):
            nonlocal target
            if start == stop:
                return
            key = (start, stop)
            if key in expanded:
                if key == gap:
                    target = len(display_rows) + 1
                rows(start, stop)
            else:
                tag = f'gap-{start}'
                for pane in panes:
                    pane.tag_configure(tag, foreground='#0969da', underline=True)
                    pane.tag_bind(tag, '<Enter>', lambda _e, p=pane: p.configure(cursor='hand2'))
                    pane.tag_bind(tag, '<Leave>', lambda _e, p=pane: p.configure(cursor='xterm'))
                    pane.tag_bind(tag, '<Button-1>', lambda _e, key=key: expand(key) or 'break')
                banner(tr('diff.context.expand', n=stop - start), extra=(tag,))

        end = 0
        for hunk in hunks:
            unchanged(end, hunk.start)
            banner(hunk.header)
            rows(hunk.start, hunk.stop)
            end = hunk.stop
        unchanged(end, len(lines))

        syncing = False

        def sync(source, first, last):
            nonlocal syncing
            if syncing:
                return
            view_scroll.set(first, last)
            syncing = True
            try:
                for pane in panes:
                    if pane is not source and abs(pane.yview()[0] - float(first)) > 1e-8:
                        pane.yview_moveto(first)
            finally:
                syncing = False

        def scroll(*args):
            for pane in panes:
                pane.yview(*args)

        view_scroll.configure(command=scroll)
        for pane in panes:
            pane.configure(state='disabled', yscrollcommand=lambda a, b, p=pane: sync(p, a, b))
            pane.yview(f'{target}.0')

    def switch():
        top = int(panes[0].index('@0,0').split('.')[0]) if panes else 1
        anchor = next((row for row in display_rows[top - 1:] if row != (None, None)), (None, None))
        render(anchor=anchor)

    if hunks:
        for value in ('unified', 'split'):
            ttk.Radiobutton(toolbar, text=tr(f'diff.mode.{value}'), variable=mode,
                            value=value, command=switch).pack(side='right', padx=4)
    render()
    window.bind('<Escape>', lambda _event: window.destroy())
    window.protocol('WM_DELETE_WINDOW', window.destroy)
    window.lift()
    window.focus_set()
    return window
