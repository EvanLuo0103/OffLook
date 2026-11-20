"""Standalone file conversion chooser, progress and result window."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable, Sequence
from tkinter import ttk

from offlook.platforms.windows_dpi import window_dpi
from offlook.ui.i18n import language, tr_in
from offlook.ui.theme import COLORS, size_window, window_fonts


class ConversionDialog(tk.Toplevel):
    """One window for the entire conversion, even with a withdrawn Tk root."""

    def __init__(self, parent: tk.Misc, options: Sequence[tuple[str, str]],
                 source_count: int, on_choose: Callable[[str], None]) -> None:
        super().__init__(parent)
        self.withdraw()
        self.source_count = source_count
        self.language_code = language()
        self._targets = tuple(options)
        self._on_choose = on_choose
        self._phase = 'choose'
        self._offlook_font_prefix = 'Convert'
        self.title(self._text('convert.dialog.title'))
        self.configure(background=COLORS['background'])
        dpi = window_dpi(self.winfo_id())
        fonts = window_fonts(self, dpi)
        size_window(self, dpi, 460, 300, 360, 240)

        pad = round(16 * dpi / 96)
        frame = ttk.Frame(self, style='Card.TFrame', padding=pad)
        frame.pack(fill='both', expand=True, padx=pad, pady=pad)
        ttk.Label(frame, text=self.title(), style='Convert.Section.TLabel').pack(anchor='w')
        self.dropdown = ttk.Combobox(frame, values=tuple(label for _, label in options),
                                     state='readonly', font=fonts['body'])
        if options:
            self.dropdown.pack(fill='x', pady=(8, 0))
            self.dropdown.current(0)

        buttons = ttk.Frame(frame, style='Card.TFrame')
        buttons.pack(side='bottom', fill='x', pady=(8, 0))
        self.convert_button = ttk.Button(buttons, text=self._text('convert.dialog.convert'),
                                         style='Convert.Accent.TButton', command=self._choose)
        if options:
            self.convert_button.pack(side='left')
        self.dismiss_button = ttk.Button(buttons, text=self._text('convert.dialog.cancel'),
                                         style='Convert.TButton', command=self._dismiss)
        self.dismiss_button.pack(side='right')

        self.summary = ttk.Label(frame, style='Convert.Card.TLabel', justify='left')
        self.summary.pack(fill='x', pady=(8, 0))
        self.summary.bind('<Configure>', self._wrap_summary)
        self._detail_frame = ttk.Frame(frame, style='Card.TFrame')
        self.details = tk.Text(self._detail_frame, wrap='word', height=3, width=1,
                               state='disabled', relief='flat', font=fonts['body'],
                               background=COLORS['card'], foreground=COLORS['text'],
                               padx=4, pady=4)
        scrollbar = ttk.Scrollbar(self._detail_frame, orient='vertical', command=self.details.yview)
        scrollbar.pack(side='right', fill='y')
        self.details.configure(yscrollcommand=scrollbar.set)
        self.details.pack(side='left', fill='both', expand=True)

        self.bind('<Map>', self._mapped)
        self.bind('<Return>', self._confirm)
        self.bind('<Escape>', self._escape)
        self.protocol('WM_DELETE_WINDOW', self._dismiss)

    def _text(self, key: str) -> str:
        return tr_in(self.language_code, key)

    def _wrap_summary(self, event: tk.Event) -> None:
        if event.width > 1:
            self.summary.configure(wraplength=event.width)

    def present(self) -> None:
        """Activate this window only, leaving the main window state untouched."""
        self.deiconify()
        self.lift()
        if self.winfo_viewable():
            self._focus_control()

    def _mapped(self, event: tk.Event) -> None:
        if event.widget is self:
            self._focus_control()

    def _focus_control(self) -> None:
        if self._phase == 'choose' and self._targets:
            self.dropdown.focus_force()
        elif self._phase == 'running':
            self.focus_force()
        else:
            self.dismiss_button.focus_force()

    def _choose(self) -> None:
        if self._phase == 'choose':
            index = self.dropdown.current()
            if 0 <= index < len(self._targets):
                self._on_choose(self._targets[index][0])

    def _dismiss(self) -> None:
        if self._phase != 'running':
            self.destroy()

    def _confirm(self, _event: tk.Event) -> str:
        if self._phase == 'result':
            self._dismiss()
        else:
            self._choose()
        return 'break'

    def _escape(self, _event: tk.Event) -> str:
        self._dismiss()
        return 'break'

    def show_running(self, text: str) -> None:
        self._phase = 'running'
        for control in (self.dropdown, self.convert_button, self.dismiss_button):
            control.state(['disabled'])
        self.summary.configure(text=text, foreground=COLORS['muted'])

    def show_result(self, summary: str, details: str = '', *, error: bool) -> None:
        self._phase = 'result'
        self.dropdown.state(['disabled'])
        self.convert_button.pack_forget()
        self.dismiss_button.configure(text=self._text('convert.dialog.close'))
        self.dismiss_button.state(['!disabled'])
        self.summary.configure(text=summary, foreground=COLORS['error' if error else 'success'])
        if details:
            self.details.configure(state='normal')
            self.details.delete('1.0', 'end')
            self.details.insert('1.0', details)
            self.details.configure(state='disabled')
            self._detail_frame.pack(fill='both', expand=True, pady=(8, 0))
        else:
            self._detail_frame.pack_forget()
