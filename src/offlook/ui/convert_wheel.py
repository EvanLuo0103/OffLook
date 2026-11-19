"""Dropdown dialog for choosing a conversion target format."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable, Sequence
from tkinter import ttk

from offlook.ui.i18n import tr


def show_conversion_wheel(
    parent: tk.Misc,
    options: Sequence[tuple[str, str]],
    on_choose: Callable[[str], None],
    on_cancel: Callable[[], None] | None = None,
) -> tk.Toplevel:
    """Show a dropdown of output formats, with a cancel choice and button."""
    window = tk.Toplevel(parent)
    window.title(tr("wheel.title"))
    window.transient(parent)
    window.resizable(False, False)

    frame = ttk.Frame(window, padding=16)
    frame.pack(fill="both", expand=True)

    ttk.Label(frame, text=tr("wheel.title")).pack(anchor="w", pady=(0, 8))

    cancel_choice = "Cancel conversion"
    choices = [cancel_choice, *(label for _extension, label in options)]
    selected = tk.StringVar(value=choices[1] if len(choices) > 1 else cancel_choice)

    dropdown = ttk.Combobox(
        frame,
        textvariable=selected,
        values=choices,
        state="readonly",
        width=32,
    )
    dropdown.pack(fill="x")
    dropdown.focus_set()

    state = {"finished": False}

    def finish(extension: str | None) -> None:
        if state["finished"]:
            return
        state["finished"] = True
        try:
            window.destroy()
        except tk.TclError:
            pass

        if extension is not None:
            on_choose(extension)
        elif on_cancel is not None:
            on_cancel()

    def convert_selected() -> None:
        index = dropdown.current()
        if index <= 0:
            finish(None)
        else:
            finish(options[index - 1][0])

    buttons = ttk.Frame(frame)
    buttons.pack(fill="x", pady=(12, 0))

    convert_button = ttk.Button(buttons, text="Convert", command=convert_selected)
    convert_button.pack(side="left")
    if not options:
        convert_button.state(["disabled"])

    ttk.Button(
        buttons,
        text="Cancel",
        command=lambda: finish(None),
    ).pack(side="right")

    window.bind("<Return>", lambda _event: convert_selected())
    window.bind("<Escape>", lambda _event: finish(None))
    window.protocol("WM_DELETE_WINDOW", lambda: finish(None))

    window.update_idletasks()
    x = parent.winfo_rootx() + (parent.winfo_width() - window.winfo_width()) // 2
    y = parent.winfo_rooty() + (parent.winfo_height() - window.winfo_height()) // 2
    window.geometry(f"+{max(0, x)}+{max(0, y)}")

    window.grab_set()
    return window
