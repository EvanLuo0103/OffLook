"""One modal chooser for an ordered pair of local files."""
from __future__ import annotations

import os
from pathlib import Path
from queue import Empty, Queue
from threading import Event, Thread
import tkinter as tk
from tkinter import ttk

from offlook.core.errors import FileAccessError
from offlook.platforms.windows_dpi import window_dpi
from offlook.platforms.windows_files import validate_local_file, validate_local_folder
from offlook.ui.i18n import tr
from offlook.ui.theme import COLORS, size_window, window_fonts


def _list_folder(value: str | Path) -> tuple[Path, list[tuple[str, bool]]]:
    folder = validate_local_folder(value)
    entries: list[tuple[str, bool]] = []
    with os.scandir(folder) as listing:
        for item in listing:
            try:
                if item.is_dir(follow_symlinks=False):
                    entries.append((item.name, True))
                elif item.is_file(follow_symlinks=False):
                    entries.append((item.name, False))
            except OSError:
                continue
    entries.sort(key=lambda entry: (not entry[1], entry[0].casefold(), entry[0]))
    return folder, entries


def _pick_worker(requests: Queue, results: Queue, closed: Event) -> None:
    while not closed.is_set():
        request = requests.get()
        if request is None or closed.is_set():
            return
        action, serial, values = request
        try:
            if action == 'folder':
                result = _list_folder(values[0])
            else:
                result = tuple(validate_local_file(value) for value in values)
        except (FileAccessError, OSError, ValueError) as exc:
            results.put((action, serial, None, str(exc)))
        else:
            results.put((action, serial, result, ''))


def pick_comparison_files(parent: tk.Misc) -> tuple[Path, Path] | None:
    """Select both paths without opening nested dialogs or doing I/O on Tk."""
    window = tk.Toplevel(parent)
    window.title(tr('btn.compare_files'))
    window.transient(parent)
    window._offlook_font_prefix = 'ComparePicker'
    dpi = window_dpi(window.winfo_id())
    window_fonts(window, dpi)
    size_window(window, dpi, 730, 530, 580, 380, monitor=parent)
    window.configure(background=COLORS['background'])
    frame = ttk.Frame(window, padding=14)
    frame.pack(fill='both', expand=True)
    frame.columnconfigure(1, weight=1)
    frame.rowconfigure(1, weight=1)

    directory, old, new, status = (tk.StringVar(window) for _ in range(4))
    requests, results = Queue(), Queue()
    closed = Event()
    serial = 0
    current: Path | None = None
    rows: dict[str, tuple[Path, bool]] = {}
    result: tuple[Path, Path] | None = None
    timer: str | None = None
    validating = False

    def label(key):
        return tr(f'compare_picker.{key}')

    def navigate(value):
        nonlocal serial
        if validating:
            return
        serial += 1
        requests.put(('folder', serial, (value,)))
        status.set(label('loading'))
        listing.delete(*listing.get_children())
        rows.clear()
        refresh()

    def up():
        if current is not None and current.parent != current:
            navigate(current.parent)

    def selected():
        return [rows[item] for item in sorted(listing.selection(), key=listing.index) if item in rows]

    def enter_selection(_event):
        items = selected()
        if len(items) == 1 and items[0][1]:
            navigate(items[0][0])
        return 'break'

    def use_one(variable):
        items = selected()
        if len(items) == 1 and not items[0][1]:
            variable.set(str(items[0][0]))

    def use_both():
        items = selected()
        if len(items) == 2 and not any(directory for _, directory in items):
            old.set(str(items[0][0]))
            new.set(str(items[1][0]))

    def refresh(*_args):
        items = selected()
        file_only = not any(is_directory for _, is_directory in items)
        for button, enabled in ((use_old, len(items) == 1 and file_only),
                                (use_new, len(items) == 1 and file_only),
                                (both, len(items) == 2 and file_only),
                                (compare, bool(old.get().strip() and new.get().strip())),
                                (go, True), (up_button, current is not None and current.parent != current),
                                (swap, bool(old.get() or new.get()))):
            button.state(['!disabled' if enabled and not validating else 'disabled'])
        for entry in entries:
            entry.state(['disabled' if validating else '!disabled'])

    def submit():
        nonlocal validating
        values = (old.get().strip(), new.get().strip())
        if validating or not all(values):
            return
        validating = True
        refresh()
        requests.put(('pair', serial, values))

    def close():
        window.destroy()

    def cleanup(event):
        nonlocal timer
        if event.widget is not window:
            return
        if timer is not None:
            window.after_cancel(timer)
            timer = None
        closed.set()
        requests.put(None)

    def poll():
        nonlocal timer, current, result, validating
        timer = None
        while True:
            try:
                action, reply, data, error = results.get_nowait()
            except Empty:
                break
            if reply != serial:
                continue
            if action == 'pair':
                if not error:
                    result = data
                    close()
                    return
                validating = False
                status.set(tr('compare_picker.file_error', reason=error))
            elif error:
                current = None
                if not validating:
                    status.set(tr('compare_picker.folder_error', reason=error))
            else:
                current, children = data
                directory.set(str(current))
                for name, is_dir in children:
                    item = listing.insert('', 'end', text=name + ('\\' if is_dir else ''))
                    rows[item] = (current / name, is_dir)
                if not validating:
                    status.set('')
            refresh()
        timer = window.after(25, poll)

    ttk.Label(frame, text=label('folder')).grid(row=0, column=0, sticky='w', padx=(0, 8))
    address = ttk.Entry(frame, textvariable=directory)
    address.grid(row=0, column=1, sticky='ew')
    address.bind('<Return>', lambda _event: navigate(directory.get()) if directory.get().strip() else None)
    go = ttk.Button(frame, text=label('go'), command=lambda: navigate(directory.get()) if directory.get().strip() else None)
    go.grid(row=0, column=2, padx=4)
    up_button = ttk.Button(frame, text=label('up'), command=up)
    up_button.grid(row=0, column=3)

    body = ttk.Frame(frame)
    body.grid(row=1, column=0, columnspan=4, sticky='nsew', pady=8)
    listing = ttk.Treeview(body, selectmode='extended', show='tree', style='ComparePicker.Treeview')
    scrollbar = ttk.Scrollbar(body, orient='vertical', command=listing.yview)
    listing.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side='right', fill='y')
    listing.pack(fill='both', expand=True)
    listing.bind('<<TreeviewSelect>>', refresh)
    listing.bind('<Double-Button-1>', enter_selection)
    listing.bind('<Return>', enter_selection)

    entries = [address]
    assign = []
    for row, (key, variable) in enumerate((('old', old), ('new', new)), 2):
        ttk.Label(frame, text=label(key)).grid(row=row, column=0, sticky='w', padx=(0, 8))
        entry = ttk.Entry(frame, textvariable=variable)
        entry.grid(row=row, column=1, sticky='ew', pady=2)
        entries.append(entry)
        button = ttk.Button(frame, text=label(f'use_{key}'), command=lambda v=variable: use_one(v))
        button.grid(row=row, column=2, columnspan=2, sticky='ew', padx=(4, 0), pady=2)
        assign.append(button)
    use_old, use_new = assign
    actions = ttk.Frame(frame)
    actions.grid(row=4, column=0, columnspan=4, sticky='ew', pady=(6, 0))
    both = ttk.Button(actions, text=label('use_both'), command=use_both)
    both.pack(side='left')

    def swap_paths():
        previous = old.get()
        old.set(new.get())
        new.set(previous)

    swap = ttk.Button(actions, text=tr('diff.swap'), command=swap_paths)
    swap.pack(side='left', padx=6)
    ttk.Label(frame, textvariable=status, wraplength=round(520 * dpi / 96)).grid(
        row=5, column=0, columnspan=4, sticky='w', pady=6)
    footer = ttk.Frame(frame)
    footer.grid(row=6, column=0, columnspan=4, sticky='ew')
    ttk.Button(footer, text=label('cancel'), command=close).pack(side='right')
    compare = ttk.Button(footer, text=label('compare'), style='Accent.TButton', command=submit)
    compare.pack(side='right', padx=6)
    for variable in (old, new):
        variable.trace_add('write', refresh)
    window.bind('<Destroy>', cleanup, add='+')
    window.bind('<Escape>', lambda _event: close())
    window.protocol('WM_DELETE_WINDOW', close)
    Thread(target=_pick_worker, args=(requests, results, closed), name='OffLookComparePicker', daemon=True).start()
    try:
        home = Path.home()
    except (OSError, RuntimeError) as exc:
        status.set(tr('compare_picker.folder_error', reason=str(exc)))
        refresh()
    else:
        directory.set(str(home))
        navigate(home)
    timer = window.after(25, poll)
    try:
        window.wait_visibility()
        window.grab_set()
        address.focus_set()
        window.wait_window()
    except tk.TclError:
        if window.winfo_exists():
            raise
    return result
