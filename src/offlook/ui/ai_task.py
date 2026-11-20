"""Shared instruction, progress, and transcript controls for the AI assistant."""
from __future__ import annotations

from collections.abc import Callable, Mapping
import tkinter as tk
from tkinter import font as tkfont, ttk

from offlook.ui.i18n import tr
from offlook.ui.theme import COLORS


def wrap_label(event: tk.Event) -> None:
    if event.width > 1:
        event.widget.configure(wraplength=event.width)


class AiTaskView(ttk.Frame):
    def __init__(self, parent: tk.Misc, *, instruction: tk.StringVar, status: tk.StringVar,
                 review_writes: tk.BooleanVar, on_run: Callable[[], None], fonts: Mapping[str, tkfont.Font],
                 style_prefix: str = '') -> None:
        super().__init__(parent, style='Card.TFrame')
        label_style = f'{style_prefix}Card.Muted.TLabel'
        prompt = ttk.Label(self, text=tr('label.ai_instruction'), style=label_style, justify='left')
        prompt.pack(fill='x')
        prompt.bind('<Configure>', wrap_label)
        self.entry = ttk.Entry(self, textvariable=instruction, style=f'{style_prefix}TEntry')
        self.entry.pack(fill='x', pady=(4, 8))
        privacy = ttk.Label(self, text=tr('hint.ai_run_privacy'), style=label_style, justify='left')
        privacy.pack(fill='x', pady=(0, 4))
        privacy.bind('<Configure>', wrap_label)
        self.review = ttk.Checkbutton(self, text=tr('check.ai_review_writes'), variable=review_writes)
        self.review.pack(anchor='w')
        self.run_button = ttk.Button(self, text=tr('btn.run_ai'), command=on_run,
                                     style=f'{style_prefix}Accent.TButton')
        self.run_button.pack(anchor='w', pady=(0, 6))
        feedback = ttk.Label(self, textvariable=status, style=label_style, justify='left')
        feedback.pack(fill='x')
        feedback.bind('<Configure>', wrap_label)
        output = ttk.Frame(self, style='Card.TFrame')
        output.pack(fill='both', expand=True, pady=(6, 0))
        self.output = tk.Text(output, height=2 if style_prefix else 8, width=1, wrap='word',
                              relief='flat', borderwidth=0, background=COLORS['card'],
                              foreground=COLORS['text'], font=fonts['body'], state='disabled', padx=4, pady=4)
        scrollbar = ttk.Scrollbar(output, orient='vertical', command=self.output.yview)
        self.output.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right', fill='y')
        self.output.pack(side='left', fill='both', expand=True)

    def focus_instruction(self) -> None:
        self.entry.focus_force()

    def set_busy(self, busy: bool) -> None:
        self.run_button.state(['disabled' if busy else '!disabled'])
        self.review.state(['disabled' if busy else '!disabled'])

    def set_output(self, value: str) -> None:
        self.output.configure(state='normal')
        self.output.delete('1.0', 'end')
        self.output.insert('1.0', value)
        self.output.configure(state='disabled')
