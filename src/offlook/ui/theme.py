"""Light card palette and per-window pixel fonts without global scaling changes."""
from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont, ttk


COLORS = {
    "background": "#F4F6FA", "card": "#FFFFFF", "text": "#182230",
    "muted": "#667085", "primary": "#2563EB", "border": "#DCE3ED",
    "error": "#B42318", "success": "#067647",
}


def apply_theme(root: tk.Tk) -> None:
    """Apply the shared clam theme once, before constructing application controls."""
    style = ttk.Style(root)
    style.theme_use("clam")
    root.configure(background=COLORS["background"])
    style.configure(".", background=COLORS["background"], foreground=COLORS["text"],
                    bordercolor=COLORS["border"], lightcolor=COLORS["border"],
                    darkcolor=COLORS["border"], focuscolor=COLORS["primary"])
    style.configure("TFrame", background=COLORS["background"])
    style.configure("Card.TFrame", background=COLORS["card"])
    style.configure("TLabel", background=COLORS["background"], foreground=COLORS["text"])
    style.configure("Card.TLabel", background=COLORS["card"])
    style.configure("Muted.TLabel", foreground=COLORS["muted"])
    style.configure("Card.Muted.TLabel", background=COLORS["card"], foreground=COLORS["muted"])
    style.configure("Title.TLabel", foreground=COLORS["text"])
    style.configure("TButton", padding=(12, 8), borderwidth=1, relief="flat")
    style.map("TButton", background=[("active", "#E8EDF5"), ("disabled", "#EEF1F6")],
              foreground=[("disabled", "#98A2B3")])
    style.configure("Accent.TButton", background=COLORS["primary"], foreground="white")
    style.map("Accent.TButton", background=[("disabled", "#A8BFF6"), ("active", "#1D4ED8")],
              foreground=[("disabled", "white"), ("active", "white")])
    style.configure("TEntry", fieldbackground=COLORS["card"], padding=6)
    style.map("TEntry", fieldbackground=[("readonly", COLORS["card"])],
              foreground=[("readonly", COLORS["text"])])
    style.configure("TCheckbutton", background=COLORS["card"], padding=4)
    style.map("TCheckbutton", background=[("active", COLORS["card"])])
    style.configure("Treeview", background=COLORS["card"], fieldbackground=COLORS["card"],
                    foreground=COLORS["text"], borderwidth=0)
    style.map("Treeview", background=[("selected", "#DBEAFE")], foreground=[("selected", COLORS["text"])])
    style.configure("Treeview.Heading", background="#EEF2F8", foreground=COLORS["text"], padding=8)


def window_fonts(window: tk.Misc, dpi: int) -> dict[str, tkfont.Font]:
    """Return/update four retained pixel fonts and fixed Main/Preview/Help styles.

    A Toplevel may set ``_offlook_font_prefix`` to ``Help``; other Toplevels
    use ``Preview``. Calling again updates existing fonts rather than accumulating
    Tcl font names. Each owner retains the returned dictionary until destruction.
    """
    prefix = getattr(window, "_offlook_font_prefix", "Main" if isinstance(window, tk.Tk) else "Preview")
    fonts = getattr(window, "_offlook_fonts", None)
    if fonts is None:
        fonts = {}
        window._offlook_fonts = fonts
    families = {name.casefold(): name for name in tkfont.families(window)}
    default = tkfont.nametofont("TkDefaultFont", root=window).actual("family")
    fixed = tkfont.nametofont("TkFixedFont", root=window).actual("family")
    def family(*choices: str) -> str:
        return next((families[name.casefold()] for name in choices if name.casefold() in families), default)
    definitions = {
        "body": (family("Microsoft JhengHei UI", "Segoe UI"), 10, "normal"),
        "title": (family("Segoe UI"), 20, "bold"),
        "section": (family("Microsoft JhengHei UI", "Segoe UI"), 12, "bold"),
        "code": (family("Consolas", fixed), 11, "normal"),
    }
    for key, (face, points, weight) in definitions.items():
        if key not in fonts:
            # Anonymous Tcl fonts are owned by this Python window, avoiding name collisions
            # when a closed Toplevel's Font destructor runs after a new preview opens.
            fonts[key] = tkfont.Font(root=window, family=face,
                                     size=-max(1, round(points * dpi / 72)), weight=weight)
        else:
            fonts[key].configure(family=face, size=-max(1, round(points * dpi / 72)), weight=weight)
    style = ttk.Style(window)
    for suffix in ("TLabel", "Card.TLabel", "Muted.TLabel", "Card.Muted.TLabel", "TButton",
                   "Accent.TButton", "TCheckbutton", "TEntry"):
        style.configure(f"{prefix}.{suffix}", font=fonts["body"])
    style.configure(f"{prefix}.Title.TLabel", font=fonts["title"])
    style.configure(f"{prefix}.Section.TLabel", font=fonts["section"], background=COLORS["card"])
    style.configure(f"{prefix}.Treeview", font=fonts["body"], rowheight=round(32 * dpi / 96))
    style.configure(f"{prefix}.Treeview.Heading", font=fonts["section"])
    if prefix == "Main":
        for suffix in ("TLabel", "Card.TLabel", "Muted.TLabel", "Card.Muted.TLabel", "TButton",
                       "Accent.TButton", "TCheckbutton", "TEntry"):
            style.configure(suffix, font=fonts["body"])
        style.configure("Title.TLabel", font=fonts["title"])
        style.configure("Section.TLabel", font=fonts["section"], background=COLORS["card"])
    return fonts


def work_area(window: tk.Misc) -> tuple[int, int, int, int]:
    """Return the current monitor work rectangle, falling back to Tk's screen."""
    try:
        import win32api
        monitor = win32api.MonitorFromWindow(window.winfo_id(), 2)
        return tuple(win32api.GetMonitorInfo(monitor)["Work"])
    except (ImportError, OSError, RuntimeError, tk.TclError):
        return 0, 0, window.winfo_screenwidth(), window.winfo_screenheight()


def size_window(window: tk.Toplevel, dpi: int, width: int, height: int,
                min_width: int, min_height: int, *, monitor: tk.Misc | None = None) -> None:
    """Fit a logical initial size and minimum to the selected monitor's work area."""
    left, top, right, bottom = work_area(monitor if monitor is not None else window)
    scale = dpi / 96
    available_width = max(1, right - left - round(32 * scale))
    available_height = max(1, bottom - top - round(64 * scale))
    actual_width = min(round(width * scale), available_width)
    actual_height = min(round(height * scale), available_height)
    window.minsize(min(round(min_width * scale), available_width), min(round(min_height * scale), available_height))
    x = left + max(0, (right - left - actual_width) // 2)
    y = top + max(0, (bottom - top - actual_height) // 2)
    window.geometry(f"{actual_width}x{actual_height}+{x}+{y}")
