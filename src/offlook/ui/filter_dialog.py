"""Non-modal file filter with an independent, read-only scan."""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from queue import Queue
import threading
import tkinter as tk
from tkinter import ttk

from offlook.core.errors import OffLookError
from offlook.core.files import FileKind
from offlook.core.search import SearchResult
from offlook.platforms.windows_dpi import window_dpi
from offlook.ui.file_results import build_result_table, fill_results
from offlook.ui.i18n import language, tr, tr_in
from offlook.ui.theme import COLORS, size_window, window_fonts

_FILTER_KIND_KEYS = {
    FileKind.IMAGE: 'kind.image', FileKind.PDF: 'kind.pdf', FileKind.TEXT: 'kind.text',
    FileKind.MARKDOWN: 'kind.markdown', FileKind.CODE: 'kind.code', FileKind.CSV: 'kind.csv',
    FileKind.DOCUMENT: 'kind.documents', FileKind.BINARY: 'kind.other',
}


def build_filter_checks(parent: tk.Misc, variables: Mapping[FileKind, tk.BooleanVar], *,
                        text: Callable[[str], str] = tr,
                        style: str = 'TCheckbutton') -> tuple[ttk.Checkbutton, ...]:
    grid = ttk.Frame(parent, style='Card.TFrame')
    grid.pack(fill='x', pady=4)
    for column in range(4):
        grid.columnconfigure(column, weight=1)
    checks = []
    for index, (kind, key) in enumerate(_FILTER_KIND_KEYS.items()):
        check = ttk.Checkbutton(grid, text=text(key), variable=variables[kind], style=style)
        check.grid(row=index // 4, column=index % 4, sticky='w', pady=2)
        checks.append(check)
    return tuple(checks)


def start_filter_scan(folder: str, kinds: tuple[FileKind, ...],
                      out: Queue[tuple[tuple[SearchResult, ...] | None, str | None]]) -> threading.Thread:
    def work() -> None:
        from offlook.core import filter_files

        try:
            out.put((filter_files(folder, kinds=kinds), None))
        except OffLookError as exc:
            out.put((None, str(exc)))
        except Exception as exc:
            out.put((None, f'File filtering failed: {type(exc).__name__}: {exc}'))

    thread = threading.Thread(target=work, name='OffLookFilter', daemon=True)
    thread.start()
    return thread


class FilterDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, folder: str | Path, *, kinds: Sequence[FileKind],
                 on_open: Callable[[str], None], on_close: Callable[[], None]) -> None:
        super().__init__(parent)
        self.withdraw()
        self.folder = Path(folder)
        self.language_code = language()
        self._on_open, self._on_close = on_open, on_close
        self._thread: threading.Thread | None = None
        self._results: Queue[tuple[tuple[SearchResult, ...] | None, str | None]] = Queue()
        self._offlook_font_prefix = 'Filter'
        self.title(self._text('card.filter'))
        self.configure(background=COLORS['background'])
        dpi = window_dpi(self.winfo_id())
        window_fonts(self, dpi)
        size_window(self, dpi, 600, 440, 450, 320)

        body = ttk.Frame(self, style='Card.TFrame', padding=round(16 * dpi / 96))
        body.pack(fill='both', expand=True)
        directory = ttk.Entry(body, style='Filter.TEntry')
        directory.insert(0, str(self.folder))
        directory.configure(state='readonly')
        directory.pack(fill='x')
        self.kind_vars = {kind: tk.BooleanVar(self, value=kind in kinds) for kind in _FILTER_KIND_KEYS}
        self._checks = build_filter_checks(body, self.kind_vars, text=self._text, style='Filter.TCheckbutton')
        self.apply_button = ttk.Button(body, text=self._text('btn.apply_filter'),
                                       style='Filter.Accent.TButton', command=self._apply)
        self.apply_button.pack(anchor='w', pady=(0, 6))
        self.status = tk.StringVar(self, value=self._text('status.filter.ready'))
        status = ttk.Label(body, textvariable=self.status, style='Filter.Card.TLabel', justify='left')
        status.pack(fill='x', pady=(0, 6))
        status.bind('<Configure>', lambda event: status.configure(wraplength=max(1, event.width)))
        self.close_button = ttk.Button(body, text=self._text('filter.dialog.close'),
                                       style='Filter.TButton', command=on_close)
        self.close_button.pack(side='bottom', anchor='e', pady=(8, 0))
        self.tree = build_result_table(body, self._open_clicked, scale=dpi / 96,
                                       style='Filter.Treeview', text=self._text, expand=True)
        self.apply_button.bind('<Return>', self._apply_from_key)
        self.tree.bind('<Return>', self._open_selected)
        self.bind('<Map>', self._mapped)
        self.bind('<Escape>', self._escape)
        self.protocol('WM_DELETE_WINDOW', on_close)

    @property
    def busy(self) -> bool:
        return self._thread is not None

    def present(self) -> None:
        self.deiconify()
        self.lift()
        if self.winfo_viewable():
            self._focus_control()

    def _text(self, key: str, **values: object) -> str:
        return tr_in(self.language_code, key, **values)

    def _mapped(self, event: tk.Event) -> None:
        if event.widget is self:
            self._focus_control()

    def _focus_control(self) -> None:
        (self.close_button if self.busy else self.apply_button).focus_force()

    def _apply_from_key(self, _event: tk.Event) -> str:
        self.apply_button.invoke()
        return 'break'

    def _apply(self) -> None:
        if self.busy:
            return
        kinds = tuple(kind for kind, variable in self.kind_vars.items() if variable.get())
        fill_results(self.tree, ())
        self._set_busy_controls(True)
        self.status.set(self._text('status.filter.running'))
        try:
            self._thread = start_filter_scan(str(self.folder), kinds, self._results)
        except RuntimeError as exc:
            self._set_busy_controls(False)
            self.status.set(f'File filtering failed: {type(exc).__name__}: {exc}')

    def _set_busy_controls(self, busy: bool) -> None:
        for control in (self.apply_button, *self._checks):
            control.state(['disabled' if busy else '!disabled'])

    def poll(self) -> None:
        if self._thread is None or self._thread.is_alive():
            return
        self._thread = None
        rows, error = self._results.get_nowait()
        self._set_busy_controls(False)
        if error is not None:
            self.status.set(error)
            return
        matches = rows or ()
        fill_results(self.tree, matches, label_kind=lambda kind: self._text(_FILTER_KIND_KEYS[kind]))
        self.status.set(self._text('status.filter.found', n=len(matches)))

    def _open_clicked(self, event: tk.Event) -> None:
        self._open_row(self.tree.identify_row(event.y))

    def _open_selected(self, _event: tk.Event) -> str:
        selected = self.tree.selection()
        if selected:
            self._open_row(selected[0])
        return 'break'

    def _open_row(self, row: str) -> None:
        if row:
            self._on_open(self.tree.item(row, 'values')[1])

    def _escape(self, _event: tk.Event) -> str:
        self._on_close()
        return 'break'
