"""Light card palette and per-window pixel fonts without global scaling changes."""
from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont, ttk


COLORS = {
    "background": "#EDF1F8", "card": "#FFFFFF", "text": "#0F172A",
    "muted": "#55607A", "primary": "#1D4ED8", "primary_dark": "#1E3A8A",
    "primary_soft": "#E3ECFF", "border": "#C7D2E4", "border_strong": "#9FB0C9",
    "field": "#FFFFFF", "error": "#B42318", "success": "#067647",
}


def apply_theme(root: tk.Tk) -> None:
    """Apply the shared clam theme once, before constructing application controls.

    Contrast rules: the window keeps a cool grey background, every card and field is
    white, and every interactive control carries a visible rim plus distinct hover
    and pressed fills. Primary actions (the main call to action on each card) use a
    solid accent fill, so "what can I click" is readable at a glance.
    """
    style = ttk.Style(root)
    style.theme_use("clam")
    root.configure(background=COLORS["background"])
    style.configure(".", background=COLORS["background"], foreground=COLORS["text"],
                    bordercolor=COLORS["border"], lightcolor=COLORS["border"],
                    darkcolor=COLORS["border"], focuscolor=COLORS["primary"])

    # Surfaces
    style.configure("TFrame", background=COLORS["background"])
    style.configure("Card.TFrame", background=COLORS["card"], borderwidth=1,
                    relief="solid", bordercolor=COLORS["border"])

    # Text
    style.configure("TLabel", background=COLORS["background"], foreground=COLORS["text"])
    style.configure("Card.TLabel", background=COLORS["card"], foreground=COLORS["text"])
    style.configure("Muted.TLabel", background=COLORS["background"], foreground=COLORS["muted"])
    style.configure("Card.Muted.TLabel", background=COLORS["card"], foreground=COLORS["muted"])
    style.configure("Title.TLabel", background=COLORS["background"], foreground=COLORS["text"])
    style.configure("Section.TLabel", background=COLORS["card"], foreground=COLORS["text"])

    # Buttons: white plate, visible rim, blue hover, clear pressed state.
    style.configure("TButton", background=COLORS["card"], foreground=COLORS["text"],
                    bordercolor=COLORS["border_strong"], lightcolor=COLORS["border_strong"],
                    darkcolor=COLORS["border_strong"], borderwidth=1, relief="solid",
                    padding=(14, 9), focusthickness=0, anchor="center")
    style.map("TButton",
              background=[("disabled", "#F2F4F9"), ("pressed", "#CBDCFB"),
                          ("active", COLORS["primary_soft"])],
              foreground=[("disabled", "#97A3B6")],
              bordercolor=[("pressed", COLORS["primary"]), ("active", COLORS["primary"])],
              lightcolor=[("active", COLORS["primary"])],
              darkcolor=[("active", COLORS["primary"])])

    style.configure("Accent.TButton", background=COLORS["primary"], foreground="#FFFFFF",
                    bordercolor=COLORS["primary_dark"], lightcolor=COLORS["primary"],
                    darkcolor=COLORS["primary_dark"], borderwidth=1, relief="solid",
                    padding=(16, 10))
    style.map("Accent.TButton",
              background=[("disabled", "#A9BFF7"), ("pressed", COLORS["primary_dark"]),
                          ("active", "#1A46BF")],
              foreground=[("disabled", "#FFFFFF"), ("active", "#FFFFFF")],
              bordercolor=[("active", COLORS["primary_dark"])])

    # Language toggle: compact segmented control at the top-right.
    style.configure("Lang.TButton", padding=(12, 4), relief="solid", borderwidth=1,
                    background=COLORS["card"], foreground=COLORS["muted"],
                    bordercolor=COLORS["border_strong"])
    style.map("Lang.TButton",
              background=[("active", COLORS["primary_soft"]), ("pressed", COLORS["primary_soft"])],
              foreground=[("active", COLORS["primary"])])
    style.configure("LangActive.TButton", padding=(12, 4), relief="solid", borderwidth=1,
                    background=COLORS["primary"], foreground="#FFFFFF",
                    bordercolor=COLORS["primary_dark"])
    style.map("LangActive.TButton",
              background=[("active", COLORS["primary_dark"]), ("pressed", COLORS["primary_dark"])],
              foreground=[("active", "#FFFFFF")])

    # Fields: white with a visible rim so they read as editable.
    style.configure("TEntry", fieldbackground=COLORS["field"], foreground=COLORS["text"],
                    bordercolor=COLORS["border_strong"], lightcolor=COLORS["border_strong"],
                    darkcolor=COLORS["border_strong"], borderwidth=1, relief="solid", padding=7)
    style.map("TEntry",
              fieldbackground=[("readonly", "#F6F8FC")],
              foreground=[("readonly", COLORS["text"])],
              bordercolor=[("focus", COLORS["primary"])],
              lightcolor=[("focus", COLORS["primary"])],
              darkcolor=[("focus", COLORS["primary"])])
    style.configure("TCombobox", fieldbackground=COLORS["field"], background=COLORS["card"],
                    foreground=COLORS["text"], arrowcolor=COLORS["primary"],
                    bordercolor=COLORS["border_strong"], lightcolor=COLORS["border_strong"],
                    darkcolor=COLORS["border_strong"], borderwidth=1, relief="solid", padding=6)
    style.map("TCombobox",
              fieldbackground=[("readonly", COLORS["field"])],
              foreground=[("readonly", COLORS["text"])],
              selectbackground=[("readonly", COLORS["primary_soft"])],
              selectforeground=[("readonly", COLORS["text"])],
              bordercolor=[("focus", COLORS["primary"])],
              lightcolor=[("focus", COLORS["primary"])],
              darkcolor=[("focus", COLORS["primary"])])
    style.configure("TCheckbutton", background=COLORS["card"], foreground=COLORS["text"],
                    padding=4, focuscolor=COLORS["primary"])
    style.map("TCheckbutton",
              background=[("active", COLORS["card"])],
              foreground=[("active", COLORS["primary"])])

    # Data views
    style.configure("Treeview", background=COLORS["card"], fieldbackground=COLORS["card"],
                    foreground=COLORS["text"], borderwidth=1, relief="solid",
                    bordercolor=COLORS["border"], rowheight=26)
    style.map("Treeview", background=[("selected", COLORS["primary_soft"])],
              foreground=[("selected", COLORS["text"])])
    style.configure("Treeview.Heading", background="#E4EBF7", foreground=COLORS["text"],
                    bordercolor=COLORS["border"], padding=8, relief="flat")

    # Scrollbars: visible trough and a thumb that reads as draggable.
    style.configure("TScrollbar", background="#C3CFE2", troughcolor="#E7EDF7",
                    bordercolor="#E7EDF7", arrowcolor=COLORS["muted"], borderwidth=0)
    style.map("TScrollbar", background=[("active", COLORS["border_strong"])])


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
                   "Accent.TButton", "TCheckbutton", "TEntry", "Lang.TButton", "LangActive.TButton"):
        style.configure(f"{prefix}.{suffix}", font=fonts["body"])
    style.configure(f"{prefix}.Title.TLabel", font=fonts["title"], background=COLORS["card"],
                    foreground=COLORS["text"])
    style.configure(f"{prefix}.Section.TLabel", font=fonts["section"], background=COLORS["card"],
                    foreground=COLORS["text"])
    style.configure(f"{prefix}.Treeview", font=fonts["body"], rowheight=round(32 * dpi / 96))
    style.configure(f"{prefix}.Treeview.Heading", font=fonts["section"])
    if prefix == "Main":
        for suffix in ("TLabel", "Card.TLabel", "Muted.TLabel", "Card.Muted.TLabel", "TButton",
                       "Accent.TButton", "TCheckbutton", "TEntry", "Lang.TButton", "LangActive.TButton"):
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
