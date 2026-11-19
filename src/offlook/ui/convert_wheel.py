"""Radial (wheel) menu for choosing a conversion target format.

The wheel is a borderless, topmost Toplevel that arranges one button per target
around a circle and closes on Esc, a background click, or focus loss. It never
performs conversion itself — it only reports the chosen format to the caller.
"""

from __future__ import annotations

import math
import tkinter as tk
from collections.abc import Callable, Sequence

from offlook.ui.i18n import tr
from offlook.ui.theme import COLORS


def show_conversion_wheel(
    parent: tk.Misc,
    options: Sequence[tuple[str, str]],
    on_choose: Callable[[str], None],
    on_cancel: Callable[[], None] | None = None,
) -> tk.Toplevel:
    """Create a radial format menu and return it; call on_choose once, then close.

    ``options`` is a sequence of ``(extension, label)`` pairs. The window centers
    itself on the current pointer position and owns a transient grab so focus
    loss reliably dismisses it.
    """
    window = tk.Toplevel(parent)
    window.overrideredirect(True)
    window.attributes("-topmost", True)
    window.configure(background=COLORS["card"])

    count = len(options)
    radius = 120 if count <= 8 else 150
    padding = 46
    center = radius + padding
    size = center * 2
    pointer_x = window.winfo_pointerx()
    pointer_y = window.winfo_pointery()
    window.geometry(f"{size}x{size}+{pointer_x - center}+{pointer_y - center}")

    canvas = tk.Canvas(window, width=size, height=size, highlightthickness=0,
                       background=COLORS["card"])
    canvas.pack(fill="both", expand=True)
    canvas.create_oval(padding // 2, padding // 2, size - padding // 2,
                       size - padding // 2, fill=COLORS["background"],
                       outline=COLORS["border"], width=2)
    canvas.create_text(center, center - 14, text=tr("wheel.title"), fill=COLORS["muted"],
                       font=("Segoe UI", 10, "bold"))
    canvas.create_text(center, center + 14, text=tr("wheel.count", n=count), fill=COLORS["muted"],
                       font=("Segoe UI", 9))

    state: dict[str, object] = {"chosen": False, "ready": False}

    def close() -> None:
        try:
            window.destroy()
        except tk.TclError:
            pass

    def finish(extension: str | None) -> None:
        if state["chosen"]:
            return
        state["chosen"] = True
        close()
        if extension is not None:
            on_choose(extension)
        elif on_cancel is not None:
            on_cancel()

    buttons: list[tk.Button] = []
    for index, (extension, label) in enumerate(options):
        angle = math.radians(-90 + 360 / count * index)
        x = center + radius * math.cos(angle)
        y = center + radius * math.sin(angle)
        button = tk.Button(window, text=label, relief="flat", borderwidth=0,
                           background=COLORS["primary"], foreground="white",
                           activebackground="#1D4ED8", activeforeground="white",
                           cursor="hand2", padx=10, pady=4,
                           command=lambda ext=extension: finish(ext))
        button.place(x=x, y=y, anchor="center")
        buttons.append(button)

    canvas.bind("<Button-1>", lambda _event: finish(None))
    window.bind("<Escape>", lambda _event: finish(None))
    window.bind("<FocusOut>", lambda _event: window.after(30, lambda: _dismiss_on_focus_out(window, state, finish)))
    window.protocol("WM_DELETE_WINDOW", lambda: finish(None))
    window.after(80, lambda: (state.update(ready=True), window.focus_force()))
    return window


def _dismiss_on_focus_out(window: tk.Toplevel, state: dict[str, object], finish: Callable[[str | None], None]) -> None:
    """Close the wheel when focus genuinely left it (not during construction)."""
    if not state.get("ready") or state.get("chosen"):
        return
    try:
        focused = window.focus_get()
    except tk.TclError:
        return
    if focused is None:
        finish(None)
