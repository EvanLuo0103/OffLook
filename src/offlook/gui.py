"""Main-thread application coordinator; parsing and native services stay off Tk."""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog, ttk
from typing import TYPE_CHECKING, Literal

from offlook.core.config import PreviewConfig
from offlook.core.errors import OffLookError
from offlook.core.files import FileKind
from offlook.core.hotkeys import parse_hotkey
from offlook.preview.models import RenderRequest
from offlook.preview.worker import WorkerRunner
from offlook.ui.ai_approval import AiApprovalDialog, RunApprovals, display_path
from offlook.ui.ai_task import AiTaskView
from offlook.ui.file_results import build_result_table, fill_results
from offlook.ui.filter_dialog import FilterDialog, build_filter_checks, start_filter_scan
from offlook.ui.i18n import language, normalize_language, set_language, tr, tr_in
from offlook.ui.theme import COLORS

if TYPE_CHECKING:
    from offlook.ui.convert_dialog import ConversionDialog


_MAIN_SIZE = (920, 680)
_MAIN_MIN_SIZE = (740, 560)

_MAIN_PAGES = (
    ('tools', 'page.tools'),
    ('search', 'card.search_filter'),
    ('ai', 'card.ai'),
    ('settings', 'page.settings'),
)


def _can_scroll(widget) -> bool:
    """Return True while a text/list/table widget still has content out of view."""
    try:
        first, last = widget.yview()
    except (tk.TclError, AttributeError, TypeError):
        return False
    return first > 0.0 or last < 1.0


@dataclass
class _PendingHotkey:
    """One candidate and the saved value against which it was requested."""

    listener: object
    persist: bool
    combo: str
    saved_combo: str


class PreviewApplication:
    """Coordinate one main window, one preview, and transactional native settings."""

    SHORTCUT_ACTIONS = {
        'preview': ('hotkey', 'action.preview'),
        'diff': ('diff_hotkey', 'action.diff'),
        'convert': ('convert_hotkey', 'action.convert'),
        'filter': ('filter_hotkey', 'action.filter'),
        'ai': ('ai_hotkey', 'action.ai'),
    }

    def __init__(self, context, *, renderers=None, resident=False, always_on_top=None,
                 background=False, config_path=None):
        """Create controls on the main thread; do not implicitly persist settings."""
        from offlook.platforms.windows_dpi import enable_high_dpi, window_dpi
        from offlook.ui.theme import apply_theme, window_fonts
        # The saved language decides every label, so resolve it before any Tk text.
        set_language(normalize_language(context.config.current.language))
        # DPI awareness must precede even hidden Tk/native windows.
        enable_high_dpi()
        self.context, self.resident = context, resident
        self.top_override = always_on_top
        self.root = tk.Tk()
        if not resident or background:
            self.root.withdraw()
        self.root.title('OffLook')
        apply_theme(self.root)
        self._dpi = window_dpi(self.root.winfo_id())
        self.root.tk.call('tk', 'scaling', self._dpi / 72)
        self.fonts = window_fonts(self.root, self._dpi)
        self._scale = self._dpi / 96
        width, height = (round(value * self._scale) for value in _MAIN_SIZE)
        self.root.geometry(f'{width}x{height}')
        self.root.minsize(*(round(value * self._scale) for value in _MAIN_MIN_SIZE))
        self.runner = WorkerRunner(renderers)
        self.listeners = {}
        self._pending_listeners = {}
        self._deferred_starts = {}
        self._retiring_listeners = []
        self._attempted_hotkeys = {}
        self._hotkey_errors = {}
        self._feedback_action = None
        self._saving_hotkeys = False
        self._observed_config = context.config.current
        self._selected_action = 'preview'
        self._drafts = {action: getattr(context.config.current, field)
                        for action, (field, _) in self.SHORTCUT_ACTIONS.items()}
        self._recording = False
        self._record_action = None
        self._record_original = ''
        self._path_thread = None
        self._path_results = queue.Queue()
        self._search_thread = None
        self._search_results = queue.Queue()
        self._diff_results = queue.Queue()
        self._diff_thread = None
        self._comparison_picker_open = False
        self._convert_thread = None
        self._convert_results = queue.Queue()
        self._ai_thread = None
        self._ai_results = queue.Queue()
        self._approvals: RunApprovals | None = None
        self._approval_request = None
        self._approval_window: AiApprovalDialog | None = None
        self.ai_quick_window: tk.Toplevel | None = None
        self._ai_quick_view: AiTaskView | None = None
        self._ai_transcript = ''
        self.convert_dialog: ConversionDialog | None = None
        self.filter_dialog: FilterDialog | None = None
        self._conversion_picker_open = False
        self.diff_window = None
        self.preview = self.path = None
        self._preview_config = None
        self._preview_opened = False
        self.generation = 0
        self.selection_hwnd = None
        self.selection_mode = None
        self.closing = False
        self.exit_code = 0
        self.tray = self.startup = self.help_window = None
        self.status = tk.StringVar(value=tr('status.initial'))
        self.shortcut_statuses = {action: tk.StringVar(value=tr('status.hotkey.disabled'))
                                  for action in self.SHORTCUT_ACTIONS}
        self.shortcut_feedback = tk.StringVar(value='')
        self.action = tk.StringVar(value=tr(self.SHORTCUT_ACTIONS['preview'][1]))
        self.combo = tk.StringVar(value=self._drafts['preview'])
        self.enabled = tk.BooleanVar(value=context.config.current.hotkey_enabled)
        self.autostart = tk.BooleanVar(value=False)
        # Values live here, not in _build_main, so a language switch can rebuild the
        # whole window without losing typed paths, settings, or status lines.
        self.diff_status = tk.StringVar(value=tr('status.diff.default'))
        self.convert_status = tk.StringVar(value=tr('status.convert.default'))
        self.convert_mode = tk.StringVar(value=context.config.current.convert_mode)
        self.search_folder = tk.StringVar()
        self.search_name = tk.StringVar()
        self.search_status = tk.StringVar(value=tr('status.search.default'))
        self.filter_shortcut_feedback = tk.StringVar(value='')
        self.search_kind_vars = {kind: tk.BooleanVar(value=False) for kind in (
            FileKind.IMAGE, FileKind.PDF, FileKind.TEXT, FileKind.MARKDOWN,
            FileKind.CODE, FileKind.CSV, FileKind.DOCUMENT, FileKind.BINARY)}
        self.ai_enabled = tk.BooleanVar(value=context.config.current.ai_enabled)
        self.ai_base_url = tk.StringVar(value=context.config.current.ai_base_url)
        self.ai_model = tk.StringVar(value=context.config.current.ai_model)
        self.ai_key = tk.StringVar()
        self.ai_key_status = tk.StringVar()
        self.ai_review_writes = tk.BooleanVar(value=False)
        if resident and context.config.has_legacy_ai_key:
            try:
                context.config.migrate_legacy_ai_key()
            except OffLookError:
                self.ai_key_status.set(tr('ai.legacy'))
        self.ai_instruction = tk.StringVar()
        self.ai_status = tk.StringVar(value=tr('status.ai.default'))
        self._search_cache = ()
        self._main_page = 'tools'
        self._build_main()
        if resident:
            from offlook.platforms.windows_startup import StartupManager
            from offlook.platforms.windows_tray import TrayIcon
            self.startup = StartupManager(context.config.path if config_path is not None else None)
            try:
                self.autostart.set(self.startup.is_enabled())
            except OffLookError as exc:
                self.status.set(str(exc))
            self.tray = TrayIcon()
            self.tray.start()
        self.root.protocol('WM_DELETE_WINDOW', self._hide if resident else self.shutdown)
        self.root.bind('<F1>', self._help_key)
        self.root.bind('<Configure>', self._main_configure)
        self.root.bind('<Unmap>', lambda event: self._cancel_approvals('main') if event.widget is self.root else None)
        self.unsubscribe = context.events.subscribe('config.changed', self._config_changed)
        if resident:
            self._reconcile_hotkeys()
        self.root.after(25, self._poll)
        self.root.after_idle(self._clamp_main)

    def _build_main(self) -> None:
        """Build fixed window controls and one scrollable workspace per task."""
        pad = round(16 * self._scale)
        gap = round(8 * self._scale)
        self._main_shell = shell = ttk.Frame(self.root)
        shell.pack(fill='both', expand=True)
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(1, weight=1)

        heading = ttk.Frame(shell, padding=(pad, gap))
        heading.grid(row=0, column=0, sticky='ew')
        heading.columnconfigure(0, weight=1)
        brand = ttk.Frame(heading)
        brand.grid(row=0, column=0, sticky='w')
        ttk.Label(brand, text='OffLook', font=self.fonts['title']).pack(anchor='w')
        ttk.Label(brand, text=tr('app.tagline'), style='Muted.TLabel').pack(anchor='w')
        ttk.Button(heading, text=tr('btn.help'), command=self._help).grid(row=0, column=1, padx=gap)
        language_bar = ttk.Frame(heading)
        language_bar.grid(row=0, column=2, sticky='e')
        for code, key in (('zh', 'lang.chinese'), ('en', 'lang.english')):
            ttk.Button(language_bar, text=tr(key),
                       style='LangActive.TButton' if language() == code else 'Lang.TButton',
                       command=lambda chosen=code: self._set_language(chosen)).pack(side='left', padx=(4, 0))

        body = ttk.Frame(shell)
        body.grid(row=1, column=0, sticky='nsew')
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, minsize=round(144 * self._scale))
        body.columnconfigure(2, weight=1)
        nav = ttk.Frame(body, padding=(gap, gap))
        nav.grid(row=0, column=0, sticky='nsew')
        ttk.Separator(body, orient='vertical').grid(row=0, column=1, sticky='ns')
        workspace = ttk.Frame(body)
        workspace.grid(row=0, column=2, sticky='nsew')
        workspace.rowconfigure(0, weight=1)
        workspace.columnconfigure(0, weight=1)
        self._pages, self._page_buttons, self._page_canvases = {}, {}, {}
        builders = (self._build_tools_page, self._build_search_page,
                    self._build_ai_page, self._build_settings_page)
        for (page, title_key), build in zip(_MAIN_PAGES, builders, strict=True):
            button = ttk.Button(nav, text=tr(title_key), width=1, style='Nav.TButton',
                                command=lambda selected=page: self._select_main_page(selected))
            button.pack(fill='x', pady=(0, gap // 2))
            self._page_buttons[page] = button
            self._pages[page], self._page_canvases[page], content = self._build_scroll_page(workspace, tr(title_key))
            build(content)
        self._select_main_page(self._main_page)

        footer = ttk.Frame(shell, padding=(pad, gap))
        footer.grid(row=2, column=0, sticky='ew')
        footer.columnconfigure(0, weight=1)
        status = ttk.Label(footer, textvariable=self.status, style='Muted.TLabel', justify='left')
        status.grid(row=0, column=0, sticky='ew', padx=(0, gap))
        status.bind('<Configure>', self._wrap_label)
        ttk.Button(footer, text=tr('btn.hide'), command=self._hide).grid(row=0, column=1, padx=(0, gap))
        ttk.Button(footer, text=tr('btn.exit'), command=self.shutdown).grid(row=0, column=2)
        self._bind_mousewheel()

    def _select_main_page(self, page: str) -> None:
        if page not in self._pages:
            return
        if self._main_page == 'ai' and page != 'ai':
            self._cancel_approvals('main')
        if self._main_page == 'settings' and page != 'settings' and self._recording:
            self._cancel_recording()
            self.shortcut_feedback.set('')
        self._main_page = page
        for key, panel in self._pages.items():
            if key == page:
                panel.grid(row=0, column=0, sticky='nsew')
            else:
                panel.grid_remove()
            self._page_buttons[key].configure(style='NavActive.TButton' if key == page else 'Nav.TButton')

    def _build_scroll_page(self, parent: ttk.Frame, title: str) -> tuple[ttk.Frame, tk.Canvas, ttk.Frame]:
        pad = round(16 * self._scale)
        page = ttk.Frame(parent)
        ttk.Label(page, text=title, style='Title.TLabel').pack(anchor='w', padx=pad, pady=(pad, 8))
        viewport = ttk.Frame(page)
        viewport.pack(fill='both', expand=True)
        canvas = tk.Canvas(viewport, width=1, height=1, highlightthickness=0, background=COLORS['background'])
        scrollbar = ttk.Scrollbar(viewport, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        # Use the page wheel handler before the scrollbar's class binding.
        scrollbar.bind('<MouseWheel>', self._wheel_main)
        scrollbar.pack(side='right', fill='y')
        canvas.pack(side='left', fill='both', expand=True)
        content = ttk.Frame(canvas, padding=(pad, 0, pad, pad))
        item = canvas.create_window(0, 0, window=content, anchor='nw')
        content.bind('<Configure>', lambda _event: canvas.configure(scrollregion=canvas.bbox(item)))
        canvas.bind('<Configure>', lambda event: canvas.itemconfigure(item, width=event.width))
        return page, canvas, content

    @staticmethod
    def _wrap_label(event: tk.Event) -> None:
        if event.width > 1:
            event.widget.configure(wraplength=event.width)

    def _card_label(self, parent: ttk.Frame, *, pady=0, muted=True, **options) -> ttk.Label:
        label = ttk.Label(parent, style='Card.Muted.TLabel' if muted else 'Card.TLabel',
                          justify='left', **options)
        label.pack(fill='x', pady=pady)
        label.bind('<Configure>', self._wrap_label)
        return label

    def _build_tools_page(self, content: ttk.Frame) -> None:
        primary = self._card(content, tr('card.preview'))
        ttk.Button(primary, text=tr('btn.choose_file'), style='Accent.TButton',
                   command=self._choose).pack(anchor='w', pady=8)
        self._card_label(primary, textvariable=self.shortcut_statuses['preview'])

        comparison = self._card(content, tr('card.compare'))
        ttk.Button(comparison, text=tr('btn.compare_files'), command=self._choose_for_diff).pack(anchor='w', pady=8)
        self._card_label(comparison, textvariable=self.shortcut_statuses['diff'])
        self._card_label(comparison, textvariable=self.diff_status, pady=(4, 0))

        conversion = self._card(content, tr('card.convert'))
        ttk.Button(conversion, text=tr('btn.choose_convert'), command=self._choose_convert_files).pack(anchor='w', pady=8)
        self._card_label(conversion, textvariable=self.shortcut_statuses['convert'])
        self._card_label(conversion, text=tr('hint.convert_shortcut'), pady=(4, 0))
        mode_row = ttk.Frame(conversion, style='Card.TFrame')
        mode_row.pack(fill='x', pady=(8, 4))
        ttk.Label(mode_row, text=tr('label.quality'), style='Card.Muted.TLabel').pack(side='left', padx=(0, 8))
        quality_box = ttk.Combobox(mode_row, textvariable=self.convert_mode, state='readonly', width=12,
                                   values=('auto', 'text', 'office'))
        quality_box.pack(side='left')
        quality_box.bind('<<ComboboxSelected>>', self._convert_mode_changed)
        self._card_label(conversion, text=tr('hint.convert_mode'))
        self._card_label(conversion, textvariable=self.convert_status, pady=(8, 0))

    def _folder_row(self, parent: ttk.Frame, folder: tk.StringVar, choose: Callable[[], None]) -> ttk.Button:
        row = ttk.Frame(parent, style='Card.TFrame')
        row.pack(fill='x', pady=4)
        button = ttk.Button(row, text=tr('btn.choose_folder'), command=choose)
        button.pack(side='left', padx=(0, 8))
        ttk.Entry(row, textvariable=folder, state='readonly', width=1).pack(side='left', fill='x', expand=True)
        return button

    def _build_search_page(self, content: ttk.Frame) -> None:
        criteria = self._card(content, tr('card.criteria'))
        self.search_folder_button = self._folder_row(criteria, self.search_folder, self._choose_search_folder)
        row = ttk.Frame(criteria, style='Card.TFrame')
        row.pack(fill='x', pady=4)
        ttk.Label(row, text=tr('label.search_name'), style='Card.Muted.TLabel').pack(side='left', padx=(0, 8))
        self.search_entry = ttk.Entry(row, textvariable=self.search_name, width=1)
        self.search_entry.pack(side='left', fill='x', expand=True)
        self._card_label(criteria, text=tr('label.search_types'), pady=(4, 0))
        self.search_checks = build_filter_checks(criteria, self.search_kind_vars)
        self.search_button = ttk.Button(criteria, text=tr('btn.search'), command=self._search, style='Accent.TButton')
        self.search_button.pack(anchor='w')
        self.search_entry.bind('<Return>', self._search_from_entry)
        self._card_label(criteria, textvariable=self.search_status, pady=(8, 0))
        self._card_label(criteria, text=tr(self.SHORTCUT_ACTIONS['filter'][1]), pady=(4, 0))
        self._card_label(criteria, textvariable=self.shortcut_statuses['filter'])
        self._card_label(criteria, textvariable=self.filter_shortcut_feedback)
        self.search_tree = build_result_table(content, self._open_search_result, scale=self._scale)
        self.search_tree.bind('<Return>', self._open_selected_search_result)

    def _search_from_entry(self, _event: tk.Event) -> str:
        self.search_button.invoke()
        return 'break'

    def _build_ai_page(self, content: ttk.Frame) -> None:
        connection = self._card(content, tr('card.ai_connection'))
        ttk.Checkbutton(connection, text=tr('check.ai_enable'), variable=self.ai_enabled).pack(anchor='w', pady=4)
        fields = ttk.Frame(connection, style='Card.TFrame')
        fields.pack(fill='x', pady=4)
        fields.columnconfigure(1, weight=1)
        for row, (label_key, variable, show) in enumerate((
            ('field.base_url', self.ai_base_url, ''),
            ('field.model', self.ai_model, ''),
            ('field.api_key', self.ai_key, '*'),
        )):
            ttk.Label(fields, text=tr(label_key), style='Card.Muted.TLabel').grid(
                row=row, column=0, sticky='w', padx=(0, 8), pady=3)
            ttk.Entry(fields, textvariable=variable, show=show).grid(row=row, column=1, sticky='ew', pady=3)
        self.ai_save_button = ttk.Button(connection, text=tr('btn.save_ai'), command=self._save_ai)
        self.ai_save_button.pack(anchor='w', pady=(4, 0))
        self.ai_remove_button = ttk.Button(connection, text=tr('ai.remove_key'), command=lambda: self._save_ai(clear=True))
        self.ai_remove_button.pack(anchor='w')
        self._refresh_ai_key_status()
        self._card_label(connection, textvariable=self.ai_key_status, pady=(4, 0))
        self._card_label(connection, textvariable=self.shortcut_statuses['ai'], pady=(4, 0))

        task = self._card(content, tr('card.ai_task'))
        self._ai_main_view = AiTaskView(task, instruction=self.ai_instruction, status=self.ai_status,
                                       review_writes=self.ai_review_writes, on_run=lambda: self._run_ai(origin='main'), fonts=self.fonts)
        self._ai_main_view.pack(fill='both', expand=True)
        self._ai_main_view.set_output(self._ai_transcript)
        self._set_ai_busy(self._ai_thread is not None)

    def _show_ai_quick(self) -> None:
        if self.closing:
            return
        window = self.ai_quick_window
        if window is None:
            from offlook.platforms.windows_dpi import window_dpi
            from offlook.ui.theme import size_window, window_fonts

            window = self.ai_quick_window = tk.Toplevel(self.root)
            window.withdraw()
            window._offlook_font_prefix = 'AiQuick'
            window.configure(background=COLORS['background'])
            dpi = window_dpi(window.winfo_id())
            window_fonts(window, dpi)
            size_window(window, dpi, 580, 400, 480, 320)
            self._build_ai_quick_body()

            def focus_when_mapped(event: tk.Event) -> None:
                if event.widget is window and self._ai_quick_view is not None:
                    self._ai_quick_view.focus_instruction()

            def dismiss(_event: tk.Event) -> str:
                self._close_ai_quick()
                return 'break'

            window.bind('<Map>', focus_when_mapped)
            window.bind('<Unmap>', lambda event: self._cancel_approvals('quick') if event.widget is window else None)
            window.bind('<Escape>', dismiss)
            window.protocol('WM_DELETE_WINDOW', self._close_ai_quick)
        window.deiconify()
        window.lift()
        if window.winfo_viewable() and self._ai_quick_view is not None:
            self._ai_quick_view.focus_instruction()

    def _build_ai_quick_body(self) -> None:
        window = self.ai_quick_window
        if window is None:
            return
        for child in window.winfo_children():
            child.destroy()
        window.title(tr('card.ai'))
        body = ttk.Frame(window, style='Card.TFrame', padding=12)
        body.pack(fill='both', expand=True)
        ttk.Button(body, text=tr('btn.close'), style='AiQuick.TButton',
                   command=self._close_ai_quick).pack(side='bottom', anchor='e', pady=(6, 0))
        hint = ttk.Label(body, text=tr('hint.ai_quick'), style='AiQuick.Card.Muted.TLabel', justify='left')
        hint.pack(fill='x', pady=(0, 6))
        hint.bind('<Configure>', self._wrap_label)
        self._ai_quick_view = AiTaskView(body, instruction=self.ai_instruction, status=self.ai_status,
                                        review_writes=self.ai_review_writes, on_run=lambda: self._run_ai(origin='quick'),
                                        fonts=window._offlook_fonts, style_prefix='AiQuick.')
        self._ai_quick_view.pack(fill='both', expand=True)
        self._ai_quick_view.set_output(self._ai_transcript)
        self._ai_quick_view.set_busy(self._ai_thread is not None)

    def _close_ai_quick(self) -> None:
        window = self.ai_quick_window
        if window is not None:
            self._cancel_approvals('quick')
            self.ai_quick_window = self._ai_quick_view = None
            window.destroy()

    def _build_settings_page(self, content: ttk.Frame) -> None:
        settings = self._card(content, tr('card.shortcuts'))
        self.enable_control = ttk.Checkbutton(settings, text=tr('check.enable_shortcuts'),
                                              variable=self.enabled, command=self._set_hotkeys_enabled)
        self.enable_control.pack(anchor='w', pady=4)
        self.action_selector = ttk.Combobox(settings, textvariable=self.action, state='readonly',
                                            values=tuple(tr(key) for _, key in self.SHORTCUT_ACTIONS.values()))
        self.action_selector.pack(fill='x', pady=4)
        self.action_selector.bind('<<ComboboxSelected>>', self._select_action)
        self.shortcut_active_label = self._card_label(settings, textvariable=self.shortcut_statuses[self._selected_action])
        self.combo_entry = ttk.Entry(settings, textvariable=self.combo, state='readonly', font=self.fonts['body'])
        self.combo_entry.pack(fill='x', pady=8)
        self.combo_entry.bind('<KeyPress>', self._capture)
        row = ttk.Frame(settings, style='Card.TFrame')
        row.pack(fill='x')
        self.record_button = ttk.Button(row, text=tr('btn.record'), command=self._record)
        self.apply_button = ttk.Button(row, text=tr('btn.apply'), command=self._apply_hotkey, style='Accent.TButton')
        self.reset_button = ttk.Button(row, text=tr('btn.reset_default'), command=self._reset_hotkey)
        for button in (self.record_button, self.apply_button, self.reset_button):
            button.pack(side='left', padx=(0, 8))
        self._card_label(settings, text=tr('hint.shortcut_keys'), pady=(8, 0))
        self._card_label(settings, text=tr('hint.shortcut_switch'), pady=(4, 0))
        self._card_label(settings, textvariable=self.shortcut_feedback, pady=(8, 0), muted=False)

        integration = self._card(content, tr('card.integration'))
        ttk.Checkbutton(integration, text=tr('check.autostart'), variable=self.autostart,
                        command=self._toggle_startup).pack(anchor='w', pady=4)
        path_row = ttk.Frame(integration, style='Card.TFrame')
        path_row.pack(anchor='w', pady=(8, 0))
        self._path_buttons = (
            ttk.Button(path_row, text=tr('btn.add_path'), command=self._change_path),
            ttk.Button(path_row, text=tr('btn.remove_path'), command=lambda: self._change_path(remove=True)),
        )
        for button in self._path_buttons:
            button.pack(side='left', padx=(0, 8))
        self._set_path_busy(self._path_thread is not None)

    def _bind_mousewheel(self):
        """Route wheel gestures over the work area to the active page's canvas.

        Binding on the toplevel lets the whole window scroll even when the
        pointer sits over a card's label or button, while widgets that already
        own a wheel gesture keep their native behaviour (see _wheel_main).
        """
        self.root.bind('<MouseWheel>', self._wheel_main)

    def _wheel_main(self, event):
        """Scroll the main window by wheel notches from anywhere in the window.

        Two cases are handled explicitly so one notch never moves two things
        and no gesture is silently swallowed:

        * a text box or result table scrolls itself while it still has hidden
          content, and otherwise falls through so the page keeps scrolling;
        * a dropdown keeps its native wheel behaviour (it changes the value).

        The page scrollbar also binds directly to this handler, so returning
        ``break`` keeps its faster class binding out of the same notch.
        """
        if self.closing:
            return None
        widget = event.widget
        if isinstance(widget, ttk.Combobox):
            return None
        if isinstance(widget, (tk.Text, tk.Listbox, ttk.Treeview)) and _can_scroll(widget):
            return None
        delta = int(getattr(event, 'delta', 0))
        if delta == 0:
            return None
        steps = -int(delta / 120) if abs(delta) >= 120 else (-1 if delta > 0 else 1)
        if steps == 0:
            return None
        self._page_canvases[self._main_page].yview_scroll(steps, 'units')
        return 'break'

    def _card(self, parent, title):
        """Create one consistently spaced surface without extra image assets."""
        card = ttk.Frame(parent, style='Card.TFrame', padding=round(16 * self._scale))
        card.pack(fill='x', pady=(0, round(12 * self._scale)))
        ttk.Label(card, text=title, style='Section.TLabel').pack(anchor='w', pady=(0, 4))
        return card

    def _main_configure(self, event):
        """Refresh only this window's fonts after an actual monitor DPI change."""
        if event.widget is not self.root:
            return
        from offlook.platforms.windows_dpi import window_dpi
        dpi=window_dpi(self.root.winfo_id())
        if dpi!=self._dpi:
            self._dpi=dpi
            from offlook.ui.theme import window_fonts
            self.fonts=window_fonts(self.root,dpi)

    def _clamp_main(self):
        """Keep controls reachable on a small monitor work area."""
        try:
            import win32api, win32gui
            work=win32api.GetMonitorInfo(win32api.MonitorFromWindow(win32gui.GetAncestor(self.root.winfo_id(),2),2))['Work']
            left,top,right,bottom=work
            width = max(1, min(round(_MAIN_SIZE[0] * self._scale), right - left - 32))
            height = max(1, min(round(_MAIN_SIZE[1] * self._scale), bottom - top - 48))
            self.root.minsize(min(width, round(_MAIN_MIN_SIZE[0] * self._scale)),
                              min(height, round(_MAIN_MIN_SIZE[1] * self._scale)))
            self.root.geometry(f'{width}x{height}+{left+16}+{top+16}')
        except Exception:
            width = min(round(_MAIN_SIZE[0] * self._scale), self.root.winfo_screenwidth())
            height = min(round(_MAIN_SIZE[1] * self._scale), self.root.winfo_screenheight())
            self.root.minsize(min(width, round(_MAIN_MIN_SIZE[0] * self._scale)),
                              min(height, round(_MAIN_MIN_SIZE[1] * self._scale)))
            self.root.geometry(f'{width}x{height}')

    def _choose(self):
        """Preview the explicitly selected local file."""
        path=filedialog.askopenfilename(parent=self.root)
        if path:
            self.open(path)

    def _choose_for_diff(self):
        """Choose both paths in one window, then start the comparison."""
        if self.closing or self._comparison_picker_open or (self._diff_thread and self._diff_thread.is_alive()):
            return
        if self.selection_mode == 'diff':
            self._cancel_selection()
        self.diff_status.set(tr('status.diff.choosing'))
        self._comparison_picker_open = True
        try:
            paths = filedialog.askopenfilenames(parent=self.root, title=tr('btn.compare_files'))
        finally:
            self._comparison_picker_open = False
        if self.closing:
            return
        if not paths:
            self.diff_status.set(tr('status.diff.cancelled'))
        elif len(paths) != 2:
            self.diff_status.set(tr('status.selection.two_files'))
        else:
            self._start_comparison(*sorted(paths, key=lambda p: (p.casefold(), p)))


    def _start_comparison(self, old_path, new_path):
        """Run two-file comparison away from the Tk thread."""
        if self._diff_thread and self._diff_thread.is_alive():
            return
        from offlook.core import compare_files
        self.diff_status.set(tr('status.diff.running'))
        def work():
            try:
                self._diff_results.put((compare_files(old_path, new_path), None))
            except OffLookError as exc:
                self._diff_results.put((None, str(exc)))
            except Exception as exc:
                self._diff_results.put((None, f'File comparison failed: {type(exc).__name__}: {exc}'))
        self._diff_thread = threading.Thread(target=work, name='OffLookFileComparison', daemon=True)
        self._diff_thread.start()

    def _choose_search_folder(self) -> None:
        if self.closing or self._search_thread is not None:
            return
        folder = filedialog.askdirectory(parent=self.root)
        if not folder or self.closing or self._search_thread is not None or folder == self.search_folder.get():
            return
        self.search_folder.set(folder)
        self._search_cache = ()
        fill_results(self.search_tree, ())
        self.search_status.set(tr('status.search.ready'))

    def _set_search_busy(self, busy: bool) -> None:
        for control in (self.search_folder_button, self.search_entry, *self.search_checks, self.search_button):
            control.state(['disabled' if busy else '!disabled'])

    def _search(self) -> None:
        if self.closing or self._search_thread is not None:
            return
        folder = self.search_folder.get()
        if not folder.strip():
            self.search_status.set(tr('status.search.no_folder'))
            return
        kinds = tuple(kind for kind, variable in self.search_kind_vars.items() if variable.get())
        self._search_cache = ()
        fill_results(self.search_tree, ())
        self._set_search_busy(True)
        self.search_status.set(tr('status.search.running'))
        try:
            self._search_thread = start_filter_scan(folder, kinds, self._search_results,
                                                    filename=self.search_name.get())
        except RuntimeError as exc:
            self._set_search_busy(False)
            self.search_status.set(f'File search failed: {type(exc).__name__}: {exc}')

    def _open_search_result(self, event: tk.Event) -> None:
        self._open_search_row(self.search_tree.identify_row(event.y))

    def _open_selected_search_result(self, _event: tk.Event) -> str:
        selected = self.search_tree.selection()
        if selected:
            self._open_search_row(selected[0])
        return 'break'

    def _open_search_row(self, row: str) -> None:
        if row:
            self.open(self.search_tree.item(row, 'values')[1])

    def _choose_convert_files(self):
        """Choose files manually without interrupting a running conversion."""
        if self._conversion_request_blocked():
            return
        if self.selection_mode == 'convert':
            self._cancel_selection()
        self._conversion_picker_open = True
        try:
            paths = filedialog.askopenfilenames(parent=self.root)
        finally:
            self._conversion_picker_open = False
        if paths:
            self._show_conversion_dialog(paths)

    def _conversion_request_blocked(self) -> bool:
        if self.closing or self._conversion_picker_open:
            return True
        if self._convert_thread is None:
            return False
        if self.convert_dialog is not None and self.convert_dialog.winfo_exists():
            self.convert_dialog.present()
        return True

    def _show_conversion_dialog(self, paths: Sequence[str | Path]) -> None:
        """Offer formats for a snapshot of the selected paths and quality."""
        if self._conversion_request_blocked():
            return
        from offlook.core.conversion import conversion_options, format_label
        from offlook.ui.convert_dialog import ConversionDialog

        sources = tuple(Path(path) for path in paths)
        mode = self.convert_mode.get().strip() or 'auto'
        status_key = None
        details = ''
        try:
            options = tuple((target, format_label(target),
                             f'{issue.source.name}: {tr(f"convert.block.{issue.code}")}' if issue else '')
                            for target, issue in conversion_options(sources, mode))
            if not options:
                status_key = 'status.convert.none'
        except OffLookError as exc:
            options = ()
            status_key = 'status.convert.failed'
            details = str(exc)

        if self.convert_dialog is not None and self.convert_dialog.winfo_exists():
            self.convert_dialog.destroy()
        dialog = ConversionDialog(self.root, options, len(sources),
                                  lambda target: self._start_conversion(sources, target, mode))
        self.convert_dialog = dialog
        if status_key is not None:
            dialog.show_result(tr_in(dialog.language_code, status_key), details, error=True)
            self.convert_status.set(tr(status_key))
        dialog.present()

    def _start_conversion(self, paths: tuple[Path, ...], target: str, mode: str) -> None:
        """Run file conversion away from Tk, keeping the chooser for its result."""
        dialog = self.convert_dialog
        if self.closing or self._convert_thread is not None or dialog is None or not dialog.winfo_exists():
            return
        values = {'n': len(paths), 'target': target.lstrip('.').upper()}
        dialog.show_running(tr_in(dialog.language_code, 'status.convert.running', **values))
        self.convert_status.set(tr('status.convert.running', **values))

        def work():
            try:
                from offlook.core import convert_files
                self._convert_results.put((convert_files(paths, target, mode=mode), None))
            except OffLookError as exc:
                self._convert_results.put((None, str(exc)))
            except Exception as exc:
                self._convert_results.put((None, f'{type(exc).__name__}: {exc}'))

        self._convert_thread = threading.Thread(target=work, name='OffLookConvert', daemon=True)
        try:
            self._convert_thread.start()
        except RuntimeError as exc:
            self._convert_thread = None
            self._report_conversion(None, f'{type(exc).__name__}: {exc}')

    def _report_conversion(self, outcomes, error: str | None) -> None:
        dialog = self.convert_dialog
        if self.closing or dialog is None:
            return
        if error is not None:
            key, details, values = 'status.convert.failed', error, {}
        else:
            outputs = [str(path.absolute()) for outcome in outcomes for path in outcome.outputs]
            key, details = 'status.convert.done', '\n'.join(outputs)
            values = {'n': dialog.source_count, 'm': len(outputs)}
        if dialog.winfo_exists():
            dialog.show_result(tr_in(dialog.language_code, key, **values), details, error=error is not None)
        self.convert_status.set(tr(key, **values))

    def _convert_mode_changed(self, _event=None):
        """Persist the conversion fidelity mode when the user changes it."""
        try:
            desired = replace(self.context.config.current, convert_mode=self.convert_mode.get().strip() or 'auto')
            self.context.config.update(desired, persist=True)
        except OffLookError as exc:
            self.convert_mode.set(self.context.config.current.convert_mode)
            self.convert_status.set(str(exc))

    def open_filter(self, folder: str | Path, *, kinds: Sequence[FileKind] = ()) -> None:
        """Show the standalone filter for an already validated directory."""
        if self.closing:
            return
        path = Path(folder)
        dialog = self.filter_dialog
        if dialog is not None:
            if dialog.busy or dialog.folder == path:
                dialog.present()
                return
            dialog.destroy()
        self.filter_dialog = FilterDialog(self.root, path, kinds=kinds, on_open=self.open,
                                          on_close=self._close_filter_dialog)
        self.filter_dialog.present()

    def _close_filter_dialog(self) -> None:
        dialog = self.filter_dialog
        if dialog is None:
            return
        if not self.resident:
            self.exit_code = 0
            self.shutdown()
        elif dialog.busy:
            dialog.withdraw()
        else:
            dialog.destroy()
            self.filter_dialog = None

    def _refresh_ai_key_status(self):
        manager = self.context.config
        self.ai_key_status.set(manager.credential_warning or tr('ai.legacy' if manager.has_legacy_ai_key else
                               'ai.key_saved' if manager.ai_credential_target else 'status.ai.no_key'))

    def _save_ai(self, *, clear=False):
        if self._ai_thread is not None:
            return
        manager = self.context.config
        key = None if clear else self.ai_key.get().strip() or None
        try:
            desired = manager.current if clear else replace(manager.current, ai_enabled=self.ai_enabled.get(),
                        ai_base_url=self.ai_base_url.get().strip(), ai_model=self.ai_model.get().strip())
            if (not key and desired.ai_base_url != manager.current.ai_base_url and
                    (manager.ai_credential_target or manager.has_legacy_ai_key)):
                self.ai_key_status.set(tr('ai.change_endpoint'))
                return
            manager.update(desired, persist=True, ai_key_action='clear' if clear else 'replace' if key else 'keep', ai_key=key)
            self.ai_key.set('')
            self._refresh_ai_key_status()
            self.status.set(manager.credential_warning or tr('status.ai.saved'))
        except OffLookError as exc:
            self.ai_key_status.set(str(exc))
            self.status.set(str(exc))

    def _run_ai(self, *, origin: Literal['main', 'quick']):
        """Run the configured AI assistant in a worker, never on the Tk thread."""
        if self.closing or self._ai_thread is not None:
            return
        instruction = self.ai_instruction.get().strip()
        if not instruction:
            self.ai_status.set(tr('status.ai.no_instruction'))
            return
        config = self.context.config.current
        target = self.context.config.ai_credential_target
        if not target:
            self.ai_status.set(tr('ai.legacy' if self.context.config.has_legacy_ai_key else 'status.ai.no_key'))
            return
        approvals = self._approvals = RunApprovals(origin) if self.ai_review_writes.get() else None
        self.ai_review_writes.set(False)
        missing = tr('ai.key_missing')
        self._set_ai_busy(True)
        self.ai_status.set(tr('status.ai.running'))
        def work():
            try:
                from offlook.core import OpenAiCompatibleProvider, default_tools, run_instruction
                from offlook.platforms.windows_credentials import read_api_key

                key = read_api_key(target)
                if not key:
                    self._ai_results.put((None, missing))
                    return
                provider = OpenAiCompatibleProvider(config.ai_base_url, key, config.ai_model)
                tools = default_tools(approve_write=approvals.request if approvals else None)
                self._ai_results.put((run_instruction(instruction, provider=provider, tools=tools), None))
            except OffLookError as exc:
                self._ai_results.put((None, str(exc)))
            except Exception as exc:
                self._ai_results.put((None, f'AI assistant failed: {type(exc).__name__}'))
        self._ai_thread = threading.Thread(target=work, name='OffLookAi', daemon=True)
        try:
            self._ai_thread.start()
        except RuntimeError as exc:
            self._ai_thread = None
            self._cancel_approvals()
            self._approvals = None
            self._set_ai_busy(False)
            self.ai_status.set(f'AI assistant failed: {type(exc).__name__}: {exc}')

    def _set_ai_busy(self, busy: bool) -> None:
        for button in (self.ai_save_button, self.ai_remove_button):
            button.state(['disabled' if busy else '!disabled'])
        self._ai_main_view.set_busy(busy)
        if self._ai_quick_view is not None:
            self._ai_quick_view.set_busy(busy)

    def _cancel_approvals(self, origin=None):
        if self._approvals is None or (origin and self._approvals.origin != origin):
            return
        self._approvals.cancel()
        self._close_approval_window()

    def _close_approval_window(self):
        self._approval_request = None
        if self._approval_window is not None:
            self._approval_window.destroy()
            self._approval_window = None

    def _approval_visible(self, approvals):
        if self.closing or approvals is not self._approvals:
            return False
        if approvals.origin == 'quick':
            return self.ai_quick_window is not None and bool(self.ai_quick_window.winfo_viewable())
        return self.root.state() not in ('withdrawn', 'iconic') and self._main_page == 'ai'

    def _poll_approval(self):
        import time

        approvals = self._approvals
        if approvals is None:
            return
        request = self._approval_request
        if request is None:
            try:
                request = approvals.requests.get_nowait()
            except queue.Empty:
                return
            self._approval_request = request
        if not approvals.is_pending(request):
            self._close_approval_window()
        elif not self._approval_visible(approvals) or time.monotonic() >= request.deadline:
            self._cancel_approvals()
        elif self._approval_window is None:
            def decide(allow):
                if request is self._approval_request:
                    approvals.decide(request, allow and self._approval_visible(approvals))
                    self._close_approval_window()
            self._approval_window = AiApprovalDialog(self.root, request.plan, decide)

    def _set_ai_output(self, value: str) -> None:
        self._ai_transcript = value
        self._ai_main_view.set_output(value)
        if self._ai_quick_view is not None:
            self._ai_quick_view.set_output(value)

    def _toggle_startup(self):
        """Change logon registration only on an explicit user action."""
        if self.startup is None:
            return
        requested=self.autostart.get()
        try:
            self.startup.set_enabled(requested)
            self.status.set(tr('status.startup.on') if requested else tr('status.startup.off'))
        except OffLookError as exc:
            self.autostart.set(not requested)
            self.status.set(str(exc))

    def _hide(self):
        """Hide only when the tray provides a usable return route."""
        if self.tray is not None and not self.tray.is_stopped:
            self._cancel_approvals('main')
            self.root.withdraw()
        else:
            self.status.set(tr('status.tray_unavailable'))

    def _show(self):
        """Restore the main controls without disrupting the preview."""
        self.root.deiconify()
        self.root.lift()

    def _set_language(self, code):
        """Switch the interface language, persist it, and rebuild the window."""
        chosen = normalize_language(code)
        if chosen == language():
            return
        previous = language()
        set_language(chosen)
        self._retranslate_defaults(previous)
        try:
            self.context.config.update(
                replace(self.context.config.current, language=chosen), persist=True)
        except OffLookError as exc:
            self.status.set(str(exc))
        self._rebuild_ui(previous)

    def _retranslate_defaults(self, previous):
        """Re-render status lines that still show their original prompt.

        Status variables hold plain text, so a language switch has to replace the
        untouched prompts while leaving live results and error messages alone.
        """
        prompts = (
            (self.status, 'status.initial'),
            (self.diff_status, 'status.diff.default'),
            (self.convert_status, 'status.convert.default'),
            *((self.search_status, f'status.search.{state}')
              for state in ('default', 'ready', 'no_folder', 'running')),
            *((self.ai_status, f'status.ai.{state}')
              for state in ('default', 'no_instruction', 'no_key', 'running', 'finished')),
        )
        for variable, key in prompts:
            if variable.get() in (tr_in(previous, key), tr(key)):
                variable.set(tr(key))

    def _rebuild_ui(self, previous: str) -> None:
        """Retranslate the window controls without losing page or task state."""
        self._cancel_approvals()
        if self._recording:
            self._cancel_recording()
            self.shortcut_feedback.set('')
        if self.help_window is not None and self.help_window.winfo_exists():
            self.help_window.destroy()
        self.help_window = None
        self._main_shell.destroy()
        self._build_main()
        self._apply_saved_toggles()
        self._set_search_busy(self._search_thread is not None)
        self._refresh_hotkey_status()
        self._repopulate_results(previous)
        self._build_ai_quick_body()

    def _apply_saved_toggles(self):
        """Re-apply control states the rebuilt widgets cannot infer on their own."""
        self.enabled.set(self.context.config.current.hotkey_enabled)
        self.convert_mode.set(self.context.config.current.convert_mode)
        self.action.set(tr(self.SHORTCUT_ACTIONS[self._selected_action][1]))
        if self.startup is not None:
            try:
                self.autostart.set(self.startup.is_enabled())
            except OffLookError:
                pass

    def _repopulate_results(self, previous: str) -> None:
        """Relabel cached rows and completed counts without replacing live feedback."""
        fill_results(self.search_tree, self._search_cache)
        count = len(self._search_cache)
        if self.search_status.get() == tr_in(previous, 'status.search.found', n=count):
            self.search_status.set(tr('status.search.found', n=count))

    def _help_key(self,event):
        """Do not steal a key while shortcut recording is active."""
        if not self._recording:
            self._help()
            return 'break'

    def _help(self):
        """Keep a single Help view whose shortcut summary follows live state."""
        if self.closing:
            return
        from offlook.ui.help import show_help
        if self.help_window is not None and self.help_window.winfo_exists():
            self.help_window.lift()
            return
        self.help_window = show_help(self.root, shortcuts=self._shortcut_summary())

    def _shortcut_summary(self):
        return {action: value.get() for action, value in self.shortcut_statuses.items()}

    def _refresh_hotkey_status(self):
        """Expose actual ownership separately from desired settings and feature results."""
        config = self.context.config.current
        separator = tr('common.separator')
        for action, (field, _) in self.SHORTCUT_ACTIONS.items():
            configured = getattr(config, field)
            active = self.listeners.get(action)
            pending = self._pending_listeners.get(action)
            deferred = self._deferred_starts.get(action)
            error = self._hotkey_errors.get(action)
            if not config.hotkey_enabled or not self.resident or self.closing:
                text = tr('status.hotkey.disabled')
            elif active is not None:
                text = active.combo
                if configured != active.combo:
                    text += separator + tr('status.hotkey.configured_inactive', combo=configured)
                if pending is not None or deferred is not None:
                    target = pending.combo if pending is not None else deferred[0]
                    text += separator + tr('status.hotkey.registering', combo=target)
                if error:
                    text += separator + tr('status.hotkey.unavailable', combo=error[0], reason=error[1])
            elif pending is not None or deferred is not None:
                target = pending.combo if pending is not None else deferred[0]
                text = tr('status.hotkey.registering', combo=target)
            else:
                reason = error[1] if error else tr('status.hotkey.not_registered')
                text = tr('status.hotkey.unavailable', combo=configured, reason=reason)
                if error and error[0] != configured:
                    text += separator + tr('status.hotkey.attempted', combo=error[0])
            self.shortcut_statuses[action].set(text)
        self._settings_busy()
        if self.help_window is not None and self.help_window.winfo_exists():
            from offlook.ui.help import update_help_shortcuts
            update_help_shortcuts(self.help_window, shortcuts=self._shortcut_summary())

    def _select_action(self, _event=None):
        """Switch only the displayed draft, never a saved binding.

        The visible selector holds a translated label, so the label is matched
        against the active language first; the combobox index is the fallback for
        callers that set the variable directly.
        """
        self._cancel_recording()
        self._drafts[self._selected_action] = self.combo.get()
        actions = tuple(self.SHORTCUT_ACTIONS)
        labels = [tr(self.SHORTCUT_ACTIONS[action][1]) for action in actions]
        chosen = self.action.get()
        if chosen in labels:
            self._selected_action = actions[labels.index(chosen)]
        else:
            index = self.action_selector.current()
            if 0 <= index < len(actions):
                self._selected_action = actions[index]
        self.combo.set(self._drafts[self._selected_action])
        self.shortcut_active_label.configure(textvariable=self.shortcut_statuses[self._selected_action])

    def _reset_hotkey(self):
        self._cancel_recording()
        field = self.SHORTCUT_ACTIONS[self._selected_action][0]
        self._drafts[self._selected_action] = getattr(PreviewConfig(), field)
        self.combo.set(self._drafts[self._selected_action])

    def _record(self):
        """Capture focused Tk events only, without a global keyboard hook."""
        self._cancel_recording()
        self._record_original = self.combo.get()
        self._record_action = self._selected_action
        self._recording = True
        self.shortcut_feedback.set(tr('status.record.press'))
        self.combo_entry.focus_set()

    def _cancel_recording(self):
        if self._recording:
            self._drafts[self._record_action] = self._record_original
            if self._record_action == self._selected_action:
                self.combo.set(self._record_original)
        self._recording = False
        self._record_action = None

    def _record_combo(self, combo):
        canonical = parse_hotkey(combo).canonical
        self._drafts[self._record_action] = canonical
        self.combo.set(canonical)
        self._recording = False
        self._record_action = None
        self.shortcut_feedback.set(tr('status.record.done'))

    def _capture(self, event):
        """Normalize a complete chord into the selected unsaved draft."""
        if not self._recording:
            return
        if event.keysym == 'Escape':
            self._cancel_recording()
            return 'break'
        if event.keysym in ('Control_L', 'Control_R', 'Alt_L', 'Alt_R', 'Shift_L', 'Shift_R'):
            return 'break'
        import win32api
        if win32api.GetAsyncKeyState(0x5B)&0x8000 or win32api.GetAsyncKeyState(0x5C)&0x8000:
            self.shortcut_feedback.set(tr('status.record.reserved'))
            return 'break'
        tokens = []
        if event.state&4: tokens.append('Ctrl')
        if event.state&(8|0x20000): tokens.append('Alt')
        if event.state&1: tokens.append('Shift')
        key = 'Space' if event.keysym == 'space' else event.keysym
        try:
            self._record_combo('+'.join(tokens + [key]))
        except OffLookError as exc:
            self.shortcut_feedback.set(str(exc))
        return 'break'

    def _settings_busy(self):
        """Disable shared controls only while registration work is unsettled."""
        busy = bool(self._pending_listeners or self._deferred_starts) or self.closing
        for widget in (self.enable_control, self.action_selector, self.record_button,
                       self.apply_button, self.reset_button):
            widget.state(['disabled'] if busy else ['!disabled'])

    def _save_hotkey_config(self, config):
        self._saving_hotkeys = True
        try:
            self.context.config.update(config, persist=True)
        finally:
            self._saving_hotkeys = False
        self._observed_config = self.context.config.current

    def _apply_hotkey(self):
        """Validate saved bindings before registration or persistence."""
        self._cancel_recording()
        action = self._selected_action
        field, label_key = self.SHORTCUT_ACTIONS[action]
        label = tr(label_key)
        self._drafts[action] = self.combo.get()
        try:
            spec = parse_hotkey(self.combo.get())
            desired = replace(self.context.config.current, **{field: spec.canonical})
            self._drafts[action] = spec.canonical
            self.combo.set(spec.canonical)
            if not desired.hotkey_enabled or not self.resident:
                self._save_hotkey_config(desired)
                self._hotkey_errors.pop(action, None)
                self.shortcut_feedback.set(tr('status.hotkey.saved_disabled', label=label))
                self._refresh_hotkey_status()
            else:
                self._begin_hotkey(action, spec.canonical, persist=True)
        except OffLookError as exc:
            self.shortcut_feedback.set(tr('status.hotkey.label', label=label, message=exc))
            self._feedback_action = action

    def _set_hotkeys_enabled(self):
        """Persist the immediate shared gate before changing native ownership."""
        config = self.context.config.current
        requested = self.enabled.get()
        try:
            self._save_hotkey_config(replace(config, hotkey_enabled=requested))
        except OffLookError as exc:
            self.enabled.set(config.hotkey_enabled)
            self.shortcut_feedback.set(str(exc))
            return
        self._cancel_recording()
        self._attempted_hotkeys.clear()
        self._hotkey_errors.clear()
        self._feedback_action = None
        self.shortcut_feedback.set(tr('status.hotkey.enabled') if requested
                                   else tr('status.hotkey.disabled'))
        self._reconcile_hotkeys()

    def _config_changed(self, event):
        """Invalidate superseded edits but preserve unrelated latest configuration."""
        config = self.context.config.current
        previous = self._observed_config
        self._observed_config = config
        if self._saving_hotkeys or self.closing:
            return
        gate_changed = config.hotkey_enabled != previous.hotkey_enabled
        changed = [action for action, (field, _) in self.SHORTCUT_ACTIONS.items()
                   if getattr(config, field) != getattr(previous, field)]
        if not gate_changed and not changed:
            return
        self._cancel_recording()
        self._drafts[self._selected_action] = self.combo.get()
        for action in changed:
            field = self.SHORTCUT_ACTIONS[action][0]
            if self._drafts[action] == getattr(previous, field):
                self._drafts[action] = getattr(config, field)
            pending = self._pending_listeners.pop(action, None)
            if pending is not None:
                self._retire(action, pending.listener)
            self._deferred_starts.pop(action, None)
            self._attempted_hotkeys.pop(action, None)
            self._hotkey_errors.pop(action, None)
        if gate_changed:
            self._attempted_hotkeys.clear()
            self._hotkey_errors.clear()
        self.combo.set(self._drafts[self._selected_action])
        self.enabled.set(config.hotkey_enabled)
        self._reconcile_hotkeys()

    def _retire(self, action, listener):
        """Retain native ownership until errors are drained and the thread stops."""
        if listener is not None:
            listener.stop()
            if not any(item is listener for _, item in self._retiring_listeners):
                self._retiring_listeners.append((action, listener))

    def _stop_hotkeys(self):
        for action, listener in self.listeners.items():
            self._retire(action, listener)
        for action, pending in self._pending_listeners.items():
            self._retire(action, pending.listener)
        self.listeners.clear()
        self._pending_listeners.clear()
        self._deferred_starts.clear()

    def _reconcile_hotkeys(self):
        """Attempt each desired binding independently, without automatic retries."""
        config = self.context.config.current
        if self.closing or not self.resident or not config.hotkey_enabled:
            self._stop_hotkeys()
        else:
            for action, (field, _) in self.SHORTCUT_ACTIONS.items():
                combo = getattr(config, field)
                active = self.listeners.get(action)
                if (action not in self._pending_listeners and action not in self._deferred_starts
                        and (active is None or active.combo != combo)
                        and self._attempted_hotkeys.get(action) != combo):
                    self._begin_hotkey(action, combo, persist=False)
        self._refresh_hotkey_status()

    def _hotkey_failed(self, action, combo, message):
        label = tr(self.SHORTCUT_ACTIONS[action][1])
        self._hotkey_errors[action] = (combo, message)
        self._feedback_action = action
        self.shortcut_feedback.set(tr('status.hotkey.failed', label=label, message=message))

    def _begin_hotkey(self, action: str, combo: str, *, persist: bool) -> None:
        """Keep the old action working until its fresh candidate is ready and saved."""
        if self.closing or action in self._pending_listeners:
            return
        config = self.context.config.current
        field = self.SHORTCUT_ACTIONS[action][0]
        label = tr(self.SHORTCUT_ACTIONS[action][1])
        combo = parse_hotkey(combo).canonical
        # Validate duplicates before any native operation, including external targets.
        replace(config, **{field: combo})
        if not self.resident or not config.hotkey_enabled:
            return
        self._attempted_hotkeys[action] = combo
        active = self.listeners.get(action)
        if active is not None and active.combo == combo and not active.is_stopped:
            try:
                if persist and getattr(config, field) != combo:
                    self._save_hotkey_config(replace(self.context.config.current, **{field: combo}))
                self._hotkey_errors.pop(action, None)
                if self._feedback_action == action:
                    self.shortcut_feedback.set(tr('status.hotkey.active', label=label))
                    self._feedback_action = None
            except OffLookError as exc:
                self._hotkey_failed(action, combo, str(exc))
            self._refresh_hotkey_status()
            return
        for owner, listener in self.listeners.items():
            if owner != action and listener.combo == combo:
                self._hotkey_failed(action, combo,
                                    tr('status.hotkey.duplicate',
                                       label=tr(self.SHORTCUT_ACTIONS[owner][1])))
                self._refresh_hotkey_status()
                return
        if any(listener.combo == combo for _, listener in self._retiring_listeners):
            self._deferred_starts[action] = (combo, persist, getattr(config, field))
            self._refresh_hotkey_status()
            return
        from offlook.platforms.windows_hotkey import HotkeyListener
        candidate = HotkeyListener(combo)
        self._pending_listeners[action] = _PendingHotkey(candidate, persist, combo, getattr(config, field))
        self._hotkey_errors.pop(action, None)
        try:
            candidate.start()
        except Exception as exc:
            self._hotkey_failed(action, combo, str(exc))
            self._retire(action, candidate)
            self._finish_hotkey(action)
        self._refresh_hotkey_status()

    def _finish_hotkey(self, action: str) -> None:
        """Settle one transaction without discarding any action's proposed draft."""
        self._pending_listeners.pop(action, None)
        self.enabled.set(self.context.config.current.hotkey_enabled)
        self.combo.set(self._drafts[self._selected_action])
        self._refresh_hotkey_status()

    def _commit_hotkey(self, action: str) -> None:
        """Patch the latest config and persist before promoting a ready candidate."""
        pending = self._pending_listeners.get(action)
        if pending is None:
            return
        config = self.context.config.current
        field = self.SHORTCUT_ACTIONS[action][0]
        label = tr(self.SHORTCUT_ACTIONS[action][1])
        if (self.closing or not self.resident or not config.hotkey_enabled
                or getattr(config, field) != pending.saved_combo):
            self._retire(action, pending.listener)
            self._finish_hotkey(action)
            self._attempted_hotkeys.pop(action, None)
            self._reconcile_hotkeys()
            return
        try:
            if pending.persist:
                self._save_hotkey_config(replace(config, **{field: pending.combo}))
            old = self.listeners.get(action)
            self.listeners[action] = pending.listener
            self._retire(action, old)
            self._hotkey_errors.pop(action, None)
            if self._feedback_action == action:
                self.shortcut_feedback.set(tr('status.hotkey.applied', label=label))
                self._feedback_action = None
        except OffLookError as exc:
            self._retire(action, pending.listener)
            self._hotkey_failed(action, pending.combo, str(exc))
        finally:
            self._finish_hotkey(action)

    def _poll_hotkeys(self):
        """Drain whole status batches before promotion or dispatch; errors win."""
        for action, listener in list(self.listeners.items()):
            events = list(listener.poll())
            errors = [event['message'] for event in events if event['type'] == 'error']
            if errors or listener.is_stopped:
                self.listeners.pop(action, None)
                self._retire(action, listener)
                field = self.SHORTCUT_ACTIONS[action][0]
                self._attempted_hotkeys[action] = getattr(self.context.config.current, field)
                self._hotkey_failed(action, listener.combo, '; '.join(errors) or 'Listener stopped')
                self._refresh_hotkey_status()
                continue
            for event in events:
                if event['type'] == 'hotkey' and not self.closing:
                    self._dispatch_hotkey(action, event['foreground_hwnd'], event.get('combo', listener.combo))
        for action, pending in list(self._pending_listeners.items()):
            events = list(pending.listener.poll())
            errors = [event['message'] for event in events if event['type'] == 'error']
            if errors or pending.listener.is_stopped:
                self._retire(action, pending.listener)
                self._hotkey_failed(action, pending.combo, '; '.join(errors) or 'Listener stopped before registration')
                self._finish_hotkey(action)
            elif not self.closing and any(event['type'] == 'ready' for event in events):
                self._commit_hotkey(action)
            # Candidate key events are always discarded, including its ready batch.
        for action, listener in self._retiring_listeners[:]:
            events = list(listener.poll())
            stopped = listener.is_stopped
            if stopped:
                # Once stopped, no producer remains: consume final unregister errors.
                events.extend(listener.poll())
            for event in events:
                if event['type'] == 'error':
                    self._hotkey_errors[action] = (listener.combo, event['message'])
                    self._feedback_action = action
                    self.shortcut_feedback.set(tr('status.hotkey.label',
                                                  label=tr(self.SHORTCUT_ACTIONS[action][1]),
                                                  message=event["message"]))
            if stopped:
                self._retiring_listeners.remove((action, listener))
            else:
                listener.stop()
            if events:
                self._refresh_hotkey_status()
        for action, (combo, persist, saved_combo) in list(self._deferred_starts.items()):
            if any(listener.combo == combo for _, listener in self._retiring_listeners):
                continue
            self._deferred_starts.pop(action)
            field = self.SHORTCUT_ACTIONS[action][0]
            if getattr(self.context.config.current, field) == saved_combo:
                self._begin_hotkey(action, combo, persist=persist)
            else:
                self._attempted_hotkeys.pop(action, None)
                self._reconcile_hotkeys()
        self._settings_busy()

    def _set_path_busy(self, busy: bool) -> None:
        for button in self._path_buttons:
            button.state(['disabled' if busy else '!disabled'])

    def _change_path(self, *, remove: bool = False) -> None:
        """Update the user PATH away from the Tk thread, one operation at a time."""
        if self.closing or self._path_thread is not None:
            return
        from offlook.platforms.windows_environment import (
            add_offlook_to_user_path, remove_offlook_from_user_path,
        )
        action = remove_offlook_from_user_path if remove else add_offlook_to_user_path
        self._set_path_busy(True)
        self.status.set(tr('status.path.updating'))

        def work():
            try:
                self._path_results.put((remove, action(), None))
            except Exception as exc:
                self._path_results.put((remove, None, str(exc)))

        self._path_thread = threading.Thread(target=work, name='OffLookPath', daemon=True)
        self._path_thread.start()

    def open(self,path: str|Path)->None:
        """Create a view; its layout callback submits the first physical-pixel request."""
        if self.closing: return
        self._cancel_selection(resume=False)
        if self.preview is not None:
            self.close_preview(exiting=False)
        from offlook.preview.window import PreviewWindow
        self.path=Path(path)
        self._preview_config=self.context.config.current
        self._preview_opened=False
        self.exit_code=0
        self.selection_hwnd = self.selection_mode = None
        self.preview=PreviewWindow(self.root,self.path,
            always_on_top=self._preview_config.always_on_top if self.top_override is None else self.top_override,
            on_render=self._submit,on_close=self.close_preview)
        self.context.events.publish('preview.requested',{'path':self.path})

    def _submit(self,page,width,height):
        """Submit device pixels directly; DPI has already been handled by the view."""
        if self.closing or self.preview is None or self.selection_hwnd is not None: return
        self.generation+=1
        self.preview.set_loading(tr('preview.updating_resolution') if self._preview_opened
                                 else tr('preview.loading'))
        self.runner.submit(RenderRequest(self.generation,self.path,self._preview_config,
                                        page_index=page,max_width=width,max_height=height))

    def _dispatch_hotkey(self, action: str, hwnd: int, combo: str) -> None:
        """Guard every feature against recording and OffLook-owned foreground views."""
        if self.closing or not hwnd:
            return
        import win32gui
        main_hwnd = win32gui.GetAncestor(self.root.winfo_id(), 2)
        if self._recording and hwnd == main_hwnd and win32gui.GetForegroundWindow() == main_hwnd:
            self._record_combo(combo)
            return
        preview_hwnd = (win32gui.GetAncestor(self.preview.window.winfo_id(), 2)
                        if self.preview is not None else None)
        owned = {main_hwnd, preview_hwnd}
        for window in (self.help_window, self.diff_window, self.convert_dialog,
                       self.filter_dialog, self.ai_quick_window, self._approval_window):
            if window is not None and window.winfo_exists():
                owned.add(win32gui.GetAncestor(window.winfo_id(), 2))
        if action == 'ai':
            if (hwnd == main_hwnd or hwnd not in owned) and win32gui.GetForegroundWindow() == hwnd:
                self._show_ai_quick()
            return
        if hwnd in owned:
            if action == 'preview' and hwnd == preview_hwnd:
                self._hotkey(hwnd)
            return
        {'preview': self._hotkey, 'diff': self._diff_hotkey,
         'convert': self._convert_hotkey, 'filter': self._filter_hotkey}[action](hwnd)

    def _hotkey(self, hwnd):
        """Toggle this preview or resolve a foreground Shell file."""
        import win32gui
        if self.preview and hwnd == win32gui.GetAncestor(self.preview.window.winfo_id(), 2):
            self.close_preview()
            return
        self._begin_selection('preview', hwnd)

    def _filter_hotkey(self, hwnd: int) -> None:
        if self.closing:
            return
        dialog = self.filter_dialog
        if dialog is not None and dialog.busy:
            dialog.present()
        else:
            self._begin_selection('filter', hwnd)

    def _diff_hotkey(self, hwnd):
        """Resolve two files from the foreground Shell view."""
        if not self._comparison_picker_open:
            self._begin_selection('diff', hwnd)

    def _begin_selection(self, action: str, hwnd: int) -> None:
        """Suspend renders before the latest captured foreground selection request."""
        if self.closing or not hwnd:
            return
        from offlook.platforms.windows_selection import SelectionRequest
        if self.preview is not None:
            self.preview.set_render_suspended(True)
        self.generation += 1
        self.selection_hwnd, self.selection_mode = hwnd, action
        self.runner.submit(SelectionRequest(self.generation, hwnd, self.context.config.current,
                                            allow_folder=action == 'filter',
                                            multiple=action in ('convert', 'diff'),
                                            strict_pair=action == 'diff'))

    def _cancel_selection(self, *, resume=True):
        if self.selection_hwnd is not None or self.selection_mode is not None:
            self.generation += 1
            self.runner.cancel()
            self.selection_hwnd = self.selection_mode = None
            if resume and self.preview is not None:
                self.preview.set_render_suspended(False)

    def _selection_feedback(self, action, message):
        label = tr(self.SHORTCUT_ACTIONS[action][1])
        if action == 'filter':
            message = message or tr('status.selection.no_folder')
        text = tr('status.hotkey.label', label=label, message=message)
        if action == 'diff':
            self.diff_status.set(text)
        elif action == 'convert':
            self.convert_status.set(text)
        elif action == 'filter':
            self.filter_shortcut_feedback.set(text)
        else:
            self.status.set(text)

    def _finish_selection(self, result):
        """Clear selection metadata on every path and resume an existing preview."""
        import win32gui
        hwnd, action = self.selection_hwnd, self.selection_mode
        self.selection_hwnd = self.selection_mode = None
        previous_preview = self.preview
        try:
            if result['code']:
                self._selection_feedback(action, result['message'])
            elif win32gui.GetForegroundWindow() != hwnd:
                self._selection_feedback(action, tr('status.selection.focus_changed'))
            elif action == 'convert':
                if result['data'].paths:
                    self._show_conversion_dialog(result['data'].paths)
                else:
                    self._selection_feedback(
                        action, result['data'].reason or tr('status.selection.no_files'))
            elif action == 'diff':
                paths, reason = result['data'].paths, result['data'].reason
                if len(paths) != 2:
                    self._selection_feedback(action, (reason if not paths else '')
                                             or tr('status.selection.two_files'))
                else:
                    self._start_comparison(*sorted(paths, key=lambda p: (str(p).casefold(), str(p))))
            elif result['data'].path is None:
                self._selection_feedback(action, result['data'].reason)
            elif action == 'filter':
                self.filter_shortcut_feedback.set('')
                self.open_filter(result['data'].path)
            else:
                self.open(result['data'].path)
        finally:
            if self.preview is not None and self.preview is previous_preview:
                self.preview.set_render_suspended(False)

    def _convert_hotkey(self, hwnd):
        """Collect every selected Explorer file for the conversion dialog."""
        if not self._conversion_request_blocked():
            self._begin_selection('convert', hwnd)

    def _poll(self):
        """Consume native events and worker results only on the owning Tk thread."""
        if self.tray:
            for event in self.tray.poll():
                if event=='exit': self.shutdown()
                elif event=='show' and not self.closing: self._show()
                elif event=='error' and not self.closing:
                    self._show()
                    self.status.set(self.tray.last_error)
        self._poll_hotkeys()
        try:
            remove, result, error = self._path_results.get_nowait()
        except queue.Empty:
            pass
        else:
            self._path_thread = None
            self._set_path_busy(False)
            if error is not None:
                self.status.set(error)
            else:
                if remove:
                    status = 'status.path.removed' if result.changed else 'status.path.not_owned'
                else:
                    status = 'status.path.added' if result.changed else 'status.path.exists'
                message = tr(status, dir=result.scripts_dir)
                if not result.broadcast_ok: message += tr('status.path.broadcast')
                if result.conflicting_executable:
                    message += tr('status.path.conflict', exe=result.conflicting_executable)
                self.status.set(message)
        if self._search_thread is not None and not self._search_thread.is_alive():
            search_results, search_error = self._search_results.get_nowait()
            self._search_thread = None
            if not self.closing:
                self._set_search_busy(False)
                self._search_cache = tuple(search_results or ())
                fill_results(self.search_tree, self._search_cache)
                self.search_status.set(search_error if search_error is not None else
                                       tr('status.search.found', n=len(self._search_cache)))
        try:
            comparison, compare_error = self._diff_results.get_nowait()
        except queue.Empty:
            pass
        else:
            if self.closing:
                pass
            elif compare_error:
                self.diff_status.set(compare_error)
            else:
                from offlook.ui.diff import show_diff
                if self.diff_window is not None and self.diff_window.winfo_exists():
                    self.diff_window.destroy()
                self.diff_window = show_diff(self.root, comparison, on_swap=lambda: self._start_comparison(
                    comparison.new_path, comparison.old_path))
                self.diff_status.set(
                    tr('status.diff.differences') if comparison.changed else tr('status.diff.same')
                )
                self.status.set(tr('status.diff.ready'))
        dialog = self.filter_dialog
        if not self.closing and dialog is not None:
            dialog.poll()
            if not dialog.busy and dialog.state() == 'withdrawn':
                dialog.destroy()
                self.filter_dialog = None
        if self._convert_thread is not None and not self._convert_thread.is_alive():
            self._convert_thread = None
            try:
                conversion, convert_error = self._convert_results.get_nowait()
            except queue.Empty:
                pass
            else:
                self._report_conversion(conversion, convert_error)
        self._poll_approval()
        if self._ai_thread is not None and not self._ai_thread.is_alive():
            ai_result, ai_error = self._ai_results.get_nowait()
            self._ai_thread = None
            self._cancel_approvals()
            self._approvals = None
            if not self.closing:
                self._set_ai_busy(False)
                if ai_error is not None:
                    self.ai_status.set(ai_error)
                    self._set_ai_output(ai_error)
                else:
                    lines = [ai_result.answer]
                    if ai_result.steps:
                        lines.extend(('', tr('status.ai.tools')))
                        for step in ai_result.steps:
                            lines.append(f'• {step.name}({step.arguments})')
                            if step.error:
                                lines.append(f'  error: {step.error}')
                            elif isinstance(step.result, dict) and 'results' in step.result:
                                for item in step.result['results']:
                                    lines.append(f"  {item['status']}: {display_path(Path(item['source']))} → "
                                                 f"{display_path(Path(item['destination']))} {item['message']}")
                    self.ai_status.set(tr('status.ai.finished'))
                    self._set_ai_output('\n'.join(lines))
        for result in self.runner.poll():
            # Every resize/page/file switch invalidates older response generations.
            if self.closing or result['request_id']!=self.generation: continue
            if self.selection_hwnd is not None:
                self._finish_selection(result)
            elif self.preview:
                if result['code']:
                    self.exit_code=1
                    self.preview.show_error(result['message'])
                    self.context.events.publish('preview.failed',{'path':self.path,'code':result['code'],'message':result['message']})
                else:
                    self.preview.show(result['data'])
                    if not self._preview_opened:
                        self._preview_opened=True
                        self.context.events.publish('preview.opened',{'file_info':result['data'].file_info})
        listeners = [*self.listeners.values(),
                     *(pending.listener for pending in self._pending_listeners.values()),
                     *(listener for _, listener in self._retiring_listeners)]
        work = (self._path_thread, self._search_thread, self._diff_thread, self._convert_thread, self._ai_thread)
        if (self.closing and self.runner.is_closed and not listeners
                and (self.tray is None or self.tray.is_stopped)
                and not any(thread is not None and thread.is_alive() for thread in work)):
            self.root.destroy()
            return
        self.root.after(25,self._poll)

    def close_preview(self, exiting=True):
        """Close the view without canceling an unrelated pending folder/diff action."""
        if self.selection_mode == 'preview':
            self._cancel_selection(resume=False)
        if self.preview is None:
            return
        if self.selection_hwnd is None:
            self.generation += 1
            self.runner.cancel()
        # destroy() calls back here; clear ownership before closing the view.
        preview, self.preview = self.preview, None
        preview.destroy()
        self.context.events.publish('preview.closed', {'path': self.path})
        if not self.resident and exiting and self.filter_dialog is None:
            self.shutdown()

    def shutdown(self):
        """Keep polling until every native listener and initiated PATH write is closed."""
        if self.closing: return
        self.closing=True
        self._cancel_approvals()
        self._cancel_recording()
        self._cancel_selection(resume=False)
        self.close_preview(exiting=False)
        self.unsubscribe()
        self.runner.close()
        self._stop_hotkeys()
        self._refresh_hotkey_status()
        if self.tray: self.tray.stop()
        self._close_ai_quick()
        if self.filter_dialog is not None:
            self.filter_dialog.destroy()
            self.filter_dialog = None
        if self.convert_dialog is not None and self.convert_dialog.winfo_exists():
            self.convert_dialog.destroy()
        if self.help_window and self.help_window.winfo_exists(): self.help_window.destroy()
        if self.diff_window and self.diff_window.winfo_exists(): self.diff_window.destroy()

    def run(self)->int:
        """Run the sole Tk loop and return the preview/interrupt exit code."""
        try:
            self.root.mainloop()
        except KeyboardInterrupt:
            self.exit_code=130
            self.shutdown()
            self.root.mainloop()
        return self.exit_code
