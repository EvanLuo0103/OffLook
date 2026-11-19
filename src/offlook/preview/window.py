"""Tk preview Toplevel: presentation only; source decoding remains in workers."""
from __future__ import annotations

import math
import re
from pathlib import Path
import tkinter as tk
from tkinter import ttk
from typing import Callable

from offlook.core.files import FileKind
from offlook.preview.models import (
    MAX_RASTER_EDGE,
    MAX_RASTER_PIXELS,
    MetadataContent,
    PreviewData,
    RasterContent,
    TableContent,
    TextContent,
)
from offlook.ui.theme import COLORS, window_fonts, size_window

from offlook.platforms.windows_dpi import window_dpi


def bounded_viewport(width: int, height: int) -> tuple[int, int]:
    """Fit a viewport into physical edge and pixel caps while preserving its ratio."""
    width = max(1, int(width))
    height = max(1, int(height))
    scale = min(1.0, MAX_RASTER_EDGE / width, MAX_RASTER_EDGE / height,
                math.sqrt(MAX_RASTER_PIXELS / (width * height)))
    result = (max(1, math.floor(width * scale)), max(1, math.floor(height * scale)))
    while result[0] * result[1] > MAX_RASTER_PIXELS:
        if result[0] >= result[1]:
            result = (result[0] - 1, result[1])
        else:
            result = (result[0], result[1] - 1)
    return result


class PreviewWindow:
    """Own a preview Toplevel and emit physical viewport requests to its parent."""

    def __init__(self, parent: tk.Tk, path: Path, *, always_on_top: bool,
                 on_render: Callable[[int, int, int], None], on_close: Callable[[], None]) -> None:
        self.parent = parent
        self.path = Path(path)
        self.on_render = on_render
        self.on_close = on_close
        self._closing = False
        self._suspended = False
        self._loading = True
        self._pending_viewport = False
        self._submitted: tuple[int, int, int] | None = None
        self._completed: tuple[int, int, int] | None = None
        self._interrupted_page: int | None = None
        self._resize_job = self._idle_job = self._fit_job = None
        self._data: PreviewData | None = None
        self._raster = self._photo = self._image = None
        self._display_size = None
        self._image_canvas = None
        self._image_item = None
        self._zoom = 1.0
        self._page_index = 0
        self.window = tk.Toplevel(parent)
        self.window._offlook_font_prefix = "Preview"
        self.window.title(f"{self.path.name} — OffLook")
        self.window.protocol("WM_DELETE_WINDOW", self.destroy)
        self.window.bind("<Escape>", lambda _event: self.destroy())
        self.window.bind("<space>", self._space)
        self._dpi = window_dpi(self.window.winfo_id())
        self._fonts = window_fonts(self.window, self._dpi)
        size_window(self.window, self._dpi, 1000, 720, 640, 440, monitor=parent)
        self.window.configure(background=COLORS["background"])
        self._build(always_on_top)
        self._layout()
        # The parent must finish assigning its view before the first request runs.
        self._idle_job = self.window.after_idle(self._initial_render)

    def _build(self, always_on_top: bool) -> None:
        self._header = ttk.Frame(self.window, style="Card.TFrame")
        self._header.pack(fill="x")
        self._header.columnconfigure(0, weight=1)
        self._title = ttk.Label(self._header, text=self.path.name, style="Preview.Title.TLabel")
        self._title.grid(row=0, column=0, sticky="w")
        self._top = tk.BooleanVar(self.window, value=always_on_top)
        ttk.Checkbutton(self._header, text="Always on top", variable=self._top, command=self._topmost,
                        style="Preview.TCheckbutton").grid(row=0, column=1, sticky="ne")
        self._info = ttk.Label(self._header, text="Local file · Offline preview", style="Preview.Card.Muted.TLabel")
        self._info.grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 4))
        self._path_entry = ttk.Entry(self._header, style="Preview.TEntry")
        self._path_entry.insert(0, str(self.path))
        self._path_entry.configure(state="readonly")
        self._path_entry.grid(row=2, column=0, columnspan=2, sticky="ew")
        self._nav = ttk.Frame(self.window, style="Card.TFrame")
        self._previous = ttk.Button(self._nav, text="Previous", command=lambda: self._page(-1), style="Preview.TButton")
        self._following = ttk.Button(self._nav, text="Next", command=lambda: self._page(1), style="Preview.TButton")
        self._page_label = ttk.Label(self._nav, style="Preview.Card.TLabel")
        self._previous.pack(side="left")
        self._page_label.pack(side="left", padx=12)
        self._following.pack(side="left")
        self._zoom_controls = ttk.Frame(self._nav, style="Card.TFrame")
        self._zoom_out = ttk.Button(self._zoom_controls, text="−", width=3,
                                    command=lambda: self._change_zoom(1 / 1.25), style="Preview.TButton")
        self._zoom_label = ttk.Label(self._zoom_controls, text="100%", width=6,
                                     style="Preview.Card.TLabel", anchor="center")
        self._zoom_in = ttk.Button(self._zoom_controls, text="+", width=3,
                                   command=lambda: self._change_zoom(1.25), style="Preview.TButton")
        self._zoom_fit = ttk.Button(self._zoom_controls, text="Fit", command=self._reset_zoom,
                                    style="Preview.TButton")
        self._zoom_out.pack(side="left", padx=(0, 4))
        self._zoom_label.pack(side="left", padx=4)
        self._zoom_in.pack(side="left", padx=4)
        self._zoom_fit.pack(side="left", padx=(4, 0))
        self._zoom_controls.pack(side="right")
        self._footer = ttk.Frame(self.window)
        self._footer.pack(side="bottom", fill="x")
        self._status = ttk.Label(self._footer, text="Loading…", style="Preview.Muted.TLabel", justify="left")
        self._status.pack(fill="x")
        ttk.Label(self._footer, text="Esc / unmodified Space to close", style="Preview.Muted.TLabel").pack(anchor="w")
        self.body = ttk.Frame(self.window, style="Card.TFrame")
        self.body.pack(fill="both", expand=True)
        self.body.bind("<Configure>", self._content_configure)
        self.window.bind("<Configure>", self._configure, add="+")
        self._topmost()

    def _px(self, value: int) -> int:
        return max(1, round(value * self._dpi / 96))

    def _layout(self) -> None:
        gap = self._px(16)
        self._padding = gap
        self._header.configure(padding=gap)
        self._header.pack_configure(padx=gap, pady=(gap, self._px(8)))
        self.body.configure(padding=gap)
        self.body.pack_configure(padx=gap, pady=(0, self._px(8)))
        if self._nav.winfo_manager():
            self._nav.pack_configure(padx=gap, pady=(0, self._px(8)))
        self._footer.pack_configure(padx=gap, pady=(0, self._px(12)))

    def _initial_render(self) -> None:
        self._idle_job = None
        if self._closing:
            return
        if self.body.winfo_width() <= self._padding * 2 + 1 or self.body.winfo_height() <= self._padding * 2 + 1:
            self._idle_job = self.window.after(25, self._initial_render)
            return
        self._request_viewport(0)

    def _space(self, event):
        """Close only for unmodified Space, keeping custom modifier shortcuts intact."""
        if not event.state & (0x1 | 0x4 | 0x20000):
            self.destroy()
            return "break"
        return None

    def _topmost(self) -> None:
        if not self._closing:
            self.window.attributes("-topmost", self._top.get())

    def _configure(self, event) -> None:
        if event.widget is not self.window or self._closing:
            return
        dpi = window_dpi(self.window.winfo_id())
        if dpi != self._dpi:
            self._dpi = dpi
            self._fonts = window_fonts(self.window, dpi)
            self._layout()
            self._schedule_resize()
        self._title.configure(wraplength=max(self._px(120), self.window.winfo_width() - self._px(200)))
        self._status.configure(wraplength=max(self._px(120), self.window.winfo_width() - self._px(40)))

    def _content_configure(self, event) -> None:
        if event.widget is self.body and not self._closing:
            self._schedule_resize()

    def _schedule_resize(self) -> None:
        if self._resize_job is not None:
            self.window.after_cancel(self._resize_job)
        self._resize_job = self.window.after(150, self._viewport_changed)

    def _viewport_changed(self) -> None:
        self._resize_job = None
        if self._closing:
            return
        self._fit_image()
        if self._suspended:
            self._pending_viewport = True
            return
        if self._raster is not None:
            page = self._submitted[0] if self._submitted is not None else self._page_index
            self._request_viewport(page)

    def _viewport(self) -> tuple[int, int]:
        # Tk sizes already represent physical pixels; do not multiply them by DPI.
        return bounded_viewport(self.body.winfo_width() - 2 * self._padding,
                                self.body.winfo_height() - 2 * self._padding)

    def _request_viewport(self, page: int) -> None:
        width, height = self._viewport()
        width, height = bounded_viewport(math.ceil(width * self._zoom), math.ceil(height * self._zoom))
        if self._suspended:
            self._pending_viewport = True
            return
        previous = self._submitted or self._completed
        if previous is not None and page == previous[0] and width <= previous[1] and height <= previous[2]:
            return
        self._pending_viewport = False
        self._submitted = (page, width, height)
        self.set_loading("Updating resolution…" if self._image is not None else "Loading…")
        self.on_render(page, width, height)

    def _change_zoom(self, factor: float) -> None:
        """Change raster magnification while retaining the current image during rerender."""
        if self._closing or self._raster is None:
            return
        self._zoom = min(4.0, max(0.25, self._zoom * factor))
        self._zoom_label.configure(text=f"{round(self._zoom * 100)}%")
        self._fit_image()
        page = self._submitted[0] if self._submitted is not None else self._page_index
        self._request_viewport(page)

    def _reset_zoom(self) -> None:
        if self._closing or self._raster is None:
            return
        self._zoom = 1.0
        self._zoom_label.configure(text="100%")
        self._fit_image()
        page = self._submitted[0] if self._submitted is not None else self._page_index
        self._request_viewport(page)

    def _page(self, offset: int) -> None:
        if self._loading or self._suspended or self._data is None or self._data.file_info.kind != FileKind.PDF:
            return
        page = self._data.page_index + offset
        if 0 <= page < self._data.page_count:
            self._request_viewport(page)

    def set_loading(self, message: str) -> None:
        """Show a loading/status message and disable page navigation."""
        if self._closing:
            return
        self._loading = True
        self._status.configure(text=message, foreground=COLORS["muted"])
        self._previous.state(["disabled"])
        self._following.state(["disabled"])

    def set_render_suspended(self, suspended: bool) -> None:
        """Pause viewport callbacks while a parent-owned file-selection task runs."""
        if self._closing:
            return
        was_suspended = self._suspended
        self._suspended = bool(suspended)
        if self._suspended and not was_suspended:
            # Selection replaces the worker request. Remember the first canceled
            # page even if more selections replace it before the preview resumes.
            if self._loading and self._submitted is not None:
                self._interrupted_page = self._submitted[0]
        elif was_suspended and not self._suspended:
            if self._interrupted_page is not None:
                page = self._interrupted_page
                self._interrupted_page = None
                # A canceled request never completed at its submitted size. Drop
                # both guards so even an unchanged/smaller viewport is retried.
                self._submitted = self._completed = None
                self._request_viewport(page)
            elif self._submitted is None or self._raster is not None:
                page = self._submitted[0] if self._submitted is not None else 0
                self._request_viewport(page)
            self._pending_viewport = False

    def show(self, data: PreviewData) -> None:
        """Present worker-bounded content without opening or decoding the source file."""
        if self._closing:
            return
        self._data = data
        self._page_index = data.page_index
        self._page_count = data.page_count
        self._loading = False
        info = data.file_info
        self._last_kind = info.kind
        self._info.configure(text=f"{info.path.name} · {info.kind.value} · {info.size_bytes:,} bytes")
        self._path_entry.configure(state="normal")
        self._path_entry.delete(0, "end")
        self._path_entry.insert(0, str(info.path))
        self._path_entry.configure(state="readonly")
        self._status.configure(text=data.notice or ("Empty file" if info.size_bytes == 0 else "Esc / Space to close"),
                               foreground=COLORS["muted"])
        self._page_label.configure(text=f"{data.page_index + 1}/{data.page_count}"
                                   if info.kind == FileKind.PDF and isinstance(data.content, RasterContent) else "")
        for child in self.body.winfo_children():
            child.destroy()
        self._image_canvas = self._image_item = None
        self._image = self._photo = None
        self._raster = data.content if isinstance(data.content, RasterContent) else None
        content = data.content
        if self._raster is not None:
            self._show_raster(self._raster)
        elif isinstance(content, MetadataContent):
            self._show_metadata(info, content, data.notice)
        elif isinstance(content, TableContent):
            self._show_table(content)
        else:
            self._show_text(content.text if isinstance(content, TextContent) else str(content))
        self._completed = self._submitted
        is_pdf = self._page_label.cget("text") != ""
        if is_pdf or self._raster is not None:
            if not self._nav.winfo_manager():
                self._nav.pack(fill="x", padx=self._padding, pady=(0, self._px(8)))
            if is_pdf:
                self._previous.pack(side="left")
                self._page_label.pack(side="left", padx=12)
                self._following.pack(side="left")
            else:
                self._previous.pack_forget()
                self._page_label.pack_forget()
                self._following.pack_forget()
        else:
            self._nav.pack_forget()
        self._zoom_controls.pack(side="right") if self._raster is not None else self._zoom_controls.pack_forget()
        self._previous.state(["!disabled"] if is_pdf and data.page_index > 0 else ["disabled"])
        self._following.state(["!disabled"] if is_pdf and data.page_index + 1 < data.page_count else ["disabled"])

    def _fit_image(self) -> None:
        """Fit the raster at 100%, then apply manual magnification with canvas scrolling."""
        if self._closing or self._image is None or self._image_canvas is None:
            return
        from PIL import Image, ImageTk
        width, height = self._viewport()
        source_w, source_h = self._image.size
        fit = min(1.0, width / source_w, height / source_h)
        scale = fit * self._zoom
        target = (max(1, math.floor(source_w * scale)), max(1, math.floor(source_h * scale)))
        if target != self._display_size:
            resampling = getattr(Image, "Resampling", Image).LANCZOS
            image = self._image if target == self._image.size else self._image.resize(target, resampling)
            try:
                self._photo = ImageTk.PhotoImage(image, master=self.window)
                self._image_canvas.itemconfigure(self._image_item, image=self._photo)
                self._display_size = target
            finally:
                if image is not self._image:
                    image.close()
        canvas_w = max(1, self._image_canvas.winfo_width())
        canvas_h = max(1, self._image_canvas.winfo_height())
        region_w, region_h = max(target[0], canvas_w), max(target[1], canvas_h)
        x = max(0, (canvas_w - target[0]) // 2)
        y = max(0, (canvas_h - target[1]) // 2)
        self._image_canvas.coords(self._image_item, x, y)
        self._image_canvas.configure(scrollregion=(0, 0, region_w, region_h))

    def _show_raster(self, raster: RasterContent) -> None:
        from PIL import Image
        self._image = Image.frombytes("RGBA", (raster.width, raster.height), raster.rgba)
        self._image_canvas = tk.Canvas(self.body, highlightthickness=0, background=COLORS["card"])
        vertical = ttk.Scrollbar(self.body, orient="vertical", command=self._image_canvas.yview)
        horizontal = ttk.Scrollbar(self.body, orient="horizontal", command=self._image_canvas.xview)
        self._image_canvas.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self._image_canvas.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        self.body.rowconfigure(0, weight=1)
        self.body.columnconfigure(0, weight=1)
        self._image_item = self._image_canvas.create_image(0, 0, anchor="nw")
        self._display_size = None
        self._fit_image()

    def _show_text(self, value: str) -> None:
        code = self._last_kind == FileKind.CODE
        self._text = tk.Text(self.body, wrap="none" if code else "word", undo=False, relief="flat", borderwidth=0,
                            font=self._fonts["code" if code else "body"], background=COLORS["card"],
                            foreground=COLORS["text"], padx=self._px(8), pady=self._px(8),
                            spacing1=self._px(2), spacing3=self._px(4))
        self._scrollable(self._text)
        self._text.insert("1.0", value)
        if self._last_kind == FileKind.MARKDOWN:
            self._markdown(self._text, value)
        self._text.configure(state="disabled")

    def _show_table(self, content: TableContent) -> None:
        columns = tuple(str(i + 1) for i in range(max((len(row) for row in content.rows), default=1)))
        table = ttk.Treeview(self.body, columns=columns, show="headings", style="Preview.Treeview")
        table.tag_configure("alternate", background="#F4F7FC")
        for col in columns:
            table.heading(col, text=col)
            table.column(col, width=self._px(160), stretch=False)
        for index, row in enumerate(content.rows):
            table.insert("", "end", values=row, tags=("alternate",) if index % 2 else ())
        self._scrollable(table)

    def _show_metadata(self, info, content: MetadataContent, notice: str) -> None:
        canvas = tk.Canvas(self.body, highlightthickness=0, background=COLORS["card"])
        scrollbar = ttk.Scrollbar(self.body, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.body.rowconfigure(0, weight=1)
        self.body.columnconfigure(0, weight=1)
        card = ttk.Frame(canvas, style="Card.TFrame", padding=self._px(8))
        item = canvas.create_window(0, 0, window=card, anchor="nw")
        card.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(item, width=event.width))
        heading = ttk.Frame(card, style="Card.TFrame")
        heading.pack(fill="x", pady=(0, self._px(16)))
        # A built-in vector icon never invokes untrusted third-party thumbnail handlers.
        icon = tk.Canvas(heading, width=self._px(88), height=self._px(104),
                         background=COLORS["card"], highlightthickness=0)
        icon.pack(side="left", padx=(0, self._px(16)))
        points = [8, 4, 56, 4, 80, 28, 80, 98, 8, 98]
        icon.create_polygon(*(self._px(n) for n in points), fill="#EFF6FF", outline=COLORS["primary"], width=self._px(2))
        icon.create_line(*(self._px(n) for n in [56, 4, 56, 28, 80, 28]), fill=COLORS["primary"], width=self._px(2))
        extension = info.extension.lstrip(".").upper()[:8] or "FILE"
        icon.create_text(self._px(44), self._px(63), text=extension, font=self._fonts["body"], fill=COLORS["primary"])
        ttk.Label(heading, text="File information", style="Preview.Section.TLabel").pack(anchor="w", pady=(self._px(12), 0))
        ttk.Label(heading, text="Safe type icon · File contents not parsed", style="Preview.Card.Muted.TLabel").pack(anchor="w", pady=self._px(8))
        kinds = {FileKind.TEXT: "Text", FileKind.MARKDOWN: "Markdown", FileKind.CODE: "Code",
                 FileKind.CSV: "CSV table", FileKind.IMAGE: "Image", FileKind.PDF: "PDF",
                 FileKind.DOCUMENT: "Document", FileKind.BINARY: "Other file"}
        values = [
            ("File name", info.path.name),
            ("Type", f"{kinds[info.kind]} / {info.extension or 'No extension'}"),
            ("Full path", str(info.path)),
            ("Folder", str(info.path.parent)),
            ("Size", f"{self._readable_size(info.size_bytes)} ({info.size_bytes:,} bytes)"),
            ("Created", self._local_time(content.created_time_ns) if content.created_time_ns is not None else "Unavailable"),
            ("Modified", self._local_time(info.modified_time_ns)),
            ("Read-only", "Yes" if content.readonly else "No"),
            ("Hidden", "Yes" if content.hidden else "No"),
            ("Reason", notice or "Content preview is not supported for this format"),
        ]
        for label, value in values:
            row = ttk.Frame(card, style="Card.TFrame")
            row.pack(fill="x", pady=self._px(4))
            ttk.Label(row, text=label, width=10, style="Preview.Card.Muted.TLabel").pack(side="left", anchor="w")
            entry = ttk.Entry(row, width=1, style="Preview.TEntry")
            entry.insert(0, value)
            entry.configure(state="readonly")
            entry.pack(side="left", fill="x", expand=True)
        def wheel(event):
            canvas.yview_scroll(-int(event.delta / 120), "units")
            return "break"
        def bind_wheel(widget):
            widget.bind("<MouseWheel>", wheel)
            for child in widget.winfo_children():
                bind_wheel(child)
        bind_wheel(card)
        canvas.bind("<MouseWheel>", wheel)

    @staticmethod
    def _readable_size(size: int) -> str:
        value = float(size)
        for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
            if value < 1024 or unit == "TiB":
                return f"{value:.0f} {unit}" if unit == "B" else f"{value:.2f} {unit}"
            value /= 1024
        raise AssertionError("unreachable size unit")

    @staticmethod
    def _local_time(value: int) -> str:
        from datetime import datetime
        try:
            return datetime.fromtimestamp(value / 1_000_000_000).astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
        except (OSError, OverflowError, ValueError):
            return "Unavailable"

    def _scrollable(self, widget) -> None:
        vertical = ttk.Scrollbar(self.body, orient="vertical", command=widget.yview)
        horizontal = ttk.Scrollbar(self.body, orient="horizontal", command=widget.xview)
        widget.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        widget.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        self.body.rowconfigure(0, weight=1)
        self.body.columnconfigure(0, weight=1)

    def _markdown(self, widget, value: str) -> None:
        for level in range(1, 7):
            widget.tag_configure(f"h{level}", font=self._fonts["section"])
        widget.tag_configure("quote", lmargin1=20, lmargin2=20)
        widget.tag_configure("list", lmargin1=12, lmargin2=24)
        widget.tag_configure("code", font=self._fonts["code"], lmargin1=12)
        fence = None
        for index, line in enumerate(value.splitlines(), 1):
            stripped = line.lstrip()
            marker = re.match(r"(`{3,}|~{3,})", stripped)
            tag = None
            if marker:
                fence = None if fence == marker[1][0] else marker[1][0]
                tag = "code"
            elif fence:
                tag = "code"
            elif match := re.match(r"^(#{1,6})\s", line):
                tag = f"h{len(match[1])}"
            elif stripped.startswith(">"):
                tag = "quote"
            elif re.match(r"^(?:[-+*]|\d+[.)])\s", stripped):
                tag = "list"
            if tag:
                widget.tag_add(tag, f"{index}.0", f"{index}.end")

    def show_error(self, message: str) -> None:
        """Display a user-facing worker error while retaining the window controls."""
        if self._closing:
            return
        self._loading = False
        self._raster = None
        self._status.configure(text=message, foreground=COLORS["error"])
        self._previous.state(["disabled"])
        self._following.state(["disabled"])

    def destroy(self) -> None:
        """Cancel local Tk callbacks, release image references, and notify the parent once."""
        if self._closing:
            return
        self._closing = True
        callback = self.on_close
        self.on_close = lambda: None
        for job in (self._idle_job, self._resize_job, self._fit_job):
            if job is not None:
                try:
                    self.window.after_cancel(job)
                except tk.TclError:
                    pass
        self._idle_job = self._resize_job = self._fit_job = None
        self._photo = self._image = self._raster = None
        try:
            self.window.destroy()
        finally:
            callback()
