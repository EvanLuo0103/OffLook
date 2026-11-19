"""Main-thread application coordinator; parsing and native services stay off Tk."""
from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog, ttk

from offlook.core.config import PreviewConfig
from offlook.core.errors import OffLookError
from offlook.core.hotkeys import parse_hotkey
from offlook.preview.models import RenderRequest
from offlook.preview.worker import WorkerRunner
from offlook.ui.theme import COLORS


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
        'preview': ('hotkey', 'Preview'),
        'search': ('search_hotkey', 'Search files'),
        'diff': ('diff_hotkey', 'Git comparison'),
        'convert': ('convert_hotkey', 'Convert files'),
    }

    def __init__(self, context, *, renderers=None, resident=False, always_on_top=None,
                 background=False, config_path=None):
        """Create controls on the main thread; do not implicitly persist settings."""
        from offlook.platforms.windows_dpi import enable_high_dpi, window_dpi
        from offlook.ui.theme import apply_theme, window_fonts
        # DPI awareness must precede even hidden Tk/native windows.
        enable_high_dpi()
        self.context, self.resident = context, resident
        self.top_override = always_on_top
        self.root = tk.Tk()
        self.root.title('OffLook')
        apply_theme(self.root)
        self._dpi = window_dpi(self.root.winfo_id())
        self.root.tk.call('tk', 'scaling', self._dpi / 72)
        self.fonts = window_fonts(self.root, self._dpi)
        self._scale = self._dpi / 96
        self.root.geometry(f'{round(720*self._scale)}x{round(620*self._scale)}')
        self.root.minsize(round(640*self._scale), round(520*self._scale))
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
        self._filter_thread = None
        self._filter_results = queue.Queue()
        self._convert_thread = None
        self._convert_results = queue.Queue()
        self._ai_thread = None
        self._ai_results = queue.Queue()
        self.convert_wheel = None
        self._convert_paths = ()
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
        self.status = tk.StringVar(value='All files stay on your device. Nothing is uploaded.')
        self.shortcut_statuses = {action: tk.StringVar(value='Disabled')
                                  for action in self.SHORTCUT_ACTIONS}
        self.shortcut_feedback = tk.StringVar(value='')
        self.action = tk.StringVar(value=self.SHORTCUT_ACTIONS['preview'][1])
        self.combo = tk.StringVar(value=self._drafts['preview'])
        self.enabled = tk.BooleanVar(value=context.config.current.hotkey_enabled)
        self.autostart = tk.BooleanVar(value=False)
        self._build_main()
        if resident:
            from offlook.platforms.windows_startup import StartupManager
            from offlook.platforms.windows_tray import TrayIcon
            self.startup = StartupManager(config_path)
            try:
                self.autostart.set(self.startup.is_enabled())
            except OffLookError as exc:
                self.status.set(str(exc))
            self.tray = TrayIcon()
            self.tray.start()
        self.root.protocol('WM_DELETE_WINDOW', self._hide if resident else self.shutdown)
        self.root.bind('<F1>', self._help_key)
        self.root.bind('<Configure>', self._main_configure)
        if not resident or background:
            self.root.withdraw()
        self.unsubscribe = context.events.subscribe('config.changed', self._config_changed)
        if resident:
            self._reconcile_hotkeys()
        self.root.after(25, self._poll)
        self.root.after_idle(self._clamp_main)

    def _build_main(self):
        """Build a scrollable card layout with a permanently reachable exit bar."""
        pad = round(24*self._scale)
        heading = ttk.Frame(self.root, padding=pad)
        heading.pack(fill='x')
        ttk.Button(heading, text='Help', command=self._help).pack(side='right')
        ttk.Label(heading, text='OffLook', font=self.fonts['title']).pack(anchor='w')
        ttk.Label(heading, text='Lightweight previews · Fully offline', style='Muted.TLabel').pack(anchor='w', pady=(4,0))
        holder = ttk.Frame(self.root)
        holder.pack(fill='both', expand=True)
        canvas = tk.Canvas(holder, highlightthickness=0, background='#F4F6FA')
        scrollbar = ttk.Scrollbar(holder, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right', fill='y')
        canvas.pack(side='left', fill='both', expand=True)
        content = ttk.Frame(canvas, padding=(pad,0,pad,pad))
        item = canvas.create_window(0,0,window=content,anchor='nw')
        self.main_canvas, self.main_content = canvas, content
        content.bind('<Configure>', lambda event: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>', lambda event: canvas.itemconfigure(item,width=event.width))
        primary = self._card(content, 'Quick preview')
        ttk.Button(primary, text='Choose file', style='Accent.TButton', command=self._choose).pack(anchor='w',pady=8)
        ttk.Label(primary, textvariable=self.shortcut_statuses['preview'], style='Card.TLabel', wraplength=560).pack(anchor='w')
        comparison = self._card(content, 'Git comparison')
        ttk.Button(comparison, text='Compare with Git HEAD', command=self._choose_for_diff).pack(anchor='w', pady=8)
        ttk.Label(comparison, textvariable=self.shortcut_statuses['diff'],
                  style='Card.Muted.TLabel', wraplength=560).pack(anchor='w')
        self.diff_status = tk.StringVar(value='Select a tracked text file to compare with Git HEAD.')
        ttk.Label(comparison, textvariable=self.diff_status, style='Card.Muted.TLabel',
                  wraplength=560).pack(anchor='w', pady=(6, 0))
        conversion = self._card(content, 'Convert files')
        ttk.Button(conversion, text='Choose files to convert', command=self._choose_convert_files).pack(anchor='w', pady=8)
        ttk.Label(conversion, text='Shortcut: Alt+C in File Explorer on one or more selected files.',
                  style='Card.Muted.TLabel', wraplength=560).pack(anchor='w')
        mode_row = ttk.Frame(conversion, style='Card.TFrame')
        mode_row.pack(fill='x', pady=4)
        ttk.Label(mode_row, text='Quality', style='Card.Muted.TLabel', width=10).pack(side='left')
        self.convert_mode = tk.StringVar(value=self.context.config.current.convert_mode)
        ttk.Combobox(mode_row, textvariable=self.convert_mode, state='readonly', width=30,
                     values=('auto', 'text', 'office'), command=self._convert_mode_changed).pack(side='left')
        ttk.Label(conversion, text='auto = keep images/layout when LibreOffice is installed · text = text-only · office = require LibreOffice',
                  style='Card.Muted.TLabel', wraplength=560).pack(anchor='w', pady=(2, 0))
        self.convert_status = tk.StringVar(value='Select files, then pick a target format from the wheel.')
        ttk.Label(conversion, textvariable=self.convert_status, style='Card.Muted.TLabel',
                  wraplength=560).pack(anchor='w', pady=(6, 0))
        search = self._card(content, 'Search files')
        self.search_card = search
        search_row = ttk.Frame(search, style='Card.TFrame')
        search_row.pack(fill='x', pady=4)
        ttk.Button(search_row, text='Choose folder', command=self._choose_search_folder).pack(side='left')
        self.search_folder = tk.StringVar()
        ttk.Label(search, textvariable=self.search_folder, style='Card.Muted.TLabel', wraplength=560).pack(anchor='w')
        filter_row = ttk.Frame(search, style='Card.TFrame')
        filter_row.pack(fill='x', pady=4)
        self.search_name = tk.StringVar()
        self.search_entry = ttk.Entry(filter_row, textvariable=self.search_name)
        self.search_entry.pack(side='left', fill='x', expand=True)
        self.search_kind = tk.StringVar(value='All types')
        ttk.Combobox(filter_row, textvariable=self.search_kind, state='readonly', width=18,
                     values=('All types', 'Text', 'Markdown', 'Code', 'CSV', 'Images', 'PDF',
                             'Documents (.doc/.xlsx)', 'Other / unknown')).pack(side='left', padx=(8, 0))
        self.search_button = ttk.Button(search, text='Search', command=self._search)
        self.search_button.pack(anchor='w', pady=(4, 8))
        self.search_tree = ttk.Treeview(search, columns=('type', 'path'), show='headings', height=6)
        self.search_tree.heading('type', text='Type')
        self.search_tree.heading('path', text='File')
        self.search_tree.column('type', width=90, stretch=False)
        self.search_tree.column('path', width=520)
        self.search_tree.pack(fill='x')
        self.search_tree.bind('<Double-1>', self._open_search_result)
        self.search_status = tk.StringVar(value='Choose a folder to search recursively.')
        ttk.Label(search, textvariable=self.search_status, style='Card.Muted.TLabel', wraplength=560).pack(anchor='w', pady=(6, 0))
        ttk.Label(search, textvariable=self.shortcut_statuses['search'],
                  style='Card.Muted.TLabel', wraplength=560).pack(anchor='w', pady=(2, 0))
        filter_card = self._card(content, 'Filter files')
        filter_row = ttk.Frame(filter_card, style='Card.TFrame')
        filter_row.pack(fill='x', pady=4)
        ttk.Button(filter_row, text='Choose folder', command=self._choose_filter_folder).pack(side='left')
        self.filter_folder = tk.StringVar()
        ttk.Label(filter_card, textvariable=self.filter_folder, style='Card.Muted.TLabel', wraplength=560).pack(anchor='w')
        from offlook.core import FileKind
        filter_options = (
            ('Images', FileKind.IMAGE), ('PDF', FileKind.PDF), ('Text', FileKind.TEXT),
            ('Markdown', FileKind.MARKDOWN), ('Code', FileKind.CODE), ('CSV', FileKind.CSV),
            ('Documents', FileKind.DOCUMENT), ('Other', FileKind.BINARY),
        )
        self.filter_vars = {}
        checkbox_grid = ttk.Frame(filter_card, style='Card.TFrame')
        checkbox_grid.pack(fill='x', pady=4)
        for index, (label, kind) in enumerate(filter_options):
            variable = tk.BooleanVar(value=False)
            self.filter_vars[kind] = variable
            ttk.Checkbutton(checkbox_grid, text=label, variable=variable).grid(
                row=index // 4, column=index % 4, sticky='w', padx=(0, 14), pady=2)
        self.filter_button = ttk.Button(filter_card, text='Apply filter', command=self._apply_filter)
        self.filter_button.pack(anchor='w', pady=(4, 8))
        self.filter_tree = ttk.Treeview(filter_card, columns=('type', 'path'), show='headings', height=6)
        self.filter_tree.heading('type', text='Type')
        self.filter_tree.heading('path', text='File')
        self.filter_tree.column('type', width=90, stretch=False)
        self.filter_tree.column('path', width=520)
        self.filter_tree.pack(fill='x')
        self.filter_tree.bind('<Double-1>', self._open_filter_result)
        self.filter_status = tk.StringVar(value='Choose a folder and check formats to filter.')
        ttk.Label(filter_card, textvariable=self.filter_status, style='Card.Muted.TLabel',
                  wraplength=560).pack(anchor='w', pady=(6, 0))
        ai_card = self._card(content, 'AI file assistant')
        self.ai_enabled = tk.BooleanVar(value=self.context.config.current.ai_enabled)
        ttk.Checkbutton(ai_card, text='Enable AI assistant', variable=self.ai_enabled).pack(anchor='w', pady=4)
        ai_grid = ttk.Frame(ai_card, style='Card.TFrame')
        ai_grid.pack(fill='x', pady=4)
        self.ai_base_url = tk.StringVar(value=self.context.config.current.ai_base_url)
        self.ai_model = tk.StringVar(value=self.context.config.current.ai_model)
        self.ai_key = tk.StringVar(value=self.context.config.current.ai_api_key)
        for row_index, (label_text, variable, show) in enumerate((
            ('Base URL', self.ai_base_url, None),
            ('Model', self.ai_model, None),
            ('API key', self.ai_key, '*'),
        )):
            ttk.Label(ai_grid, text=label_text, style='Card.Muted.TLabel', width=10).grid(
                row=row_index, column=0, sticky='w', pady=3)
            ttk.Entry(ai_grid, textvariable=variable, show=show or '').grid(
                row=row_index, column=1, sticky='ew', pady=3)
        ai_grid.columnconfigure(1, weight=1)
        ttk.Button(ai_card, text='Save AI settings', command=self._save_ai).pack(anchor='w', pady=(4, 8))
        ttk.Label(ai_card, text='Instruction (e.g. "move all PDF files in D:\\Docs to D:\\Archive")',
                  style='Card.Muted.TLabel', wraplength=560).pack(anchor='w')
        self.ai_instruction = ttk.Entry(ai_card)
        self.ai_instruction.pack(fill='x', pady=6)
        self.ai_run_button = ttk.Button(ai_card, text='Run with AI', command=self._run_ai)
        self.ai_run_button.pack(anchor='w', pady=(0, 8))
        self.ai_status = tk.StringVar(value='Connect your own AI (DeepSeek, OpenAI, or any compatible endpoint).')
        ttk.Label(ai_card, textvariable=self.ai_status, style='Card.Muted.TLabel',
                  wraplength=560).pack(anchor='w')
        self.ai_output = tk.Text(ai_card, height=6, wrap='word', relief='flat', borderwidth=0,
                                 background=COLORS['card'], foreground=COLORS['text'],
                                 font=self.fonts['body'], state='disabled', padx=4, pady=4)
        self.ai_output.pack(fill='x', pady=(6, 0))
        settings = self._card(content, 'Shortcut settings')
        self.enable_control = ttk.Checkbutton(settings, text='Enable global shortcuts',
                                               variable=self.enabled, command=self._set_hotkeys_enabled)
        self.enable_control.pack(anchor='w', pady=4)
        self.action_selector = ttk.Combobox(settings, textvariable=self.action, state='readonly',
                                            values=tuple(label for _, label in self.SHORTCUT_ACTIONS.values()))
        self.action_selector.pack(fill='x', pady=4)
        self.action_selector.bind('<<ComboboxSelected>>', self._select_action)
        self.combo_entry = ttk.Entry(settings,textvariable=self.combo,state='readonly',font=self.fonts['body'])
        self.combo_entry.pack(fill='x',pady=6)
        self.combo_entry.bind('<KeyPress>', self._capture)
        row=ttk.Frame(settings,style='Card.TFrame')
        row.pack(fill='x')
        self.record_button=ttk.Button(row,text='Record shortcut',command=self._record)
        self.apply_button=ttk.Button(row,text='Apply',command=self._apply_hotkey)
        self.reset_button=ttk.Button(row,text='Reset default',command=self._reset_hotkey)
        for button in (self.record_button,self.apply_button,self.reset_button):
            button.pack(side='left',padx=(0,8))
        ttk.Label(settings,text='Ctrl or Alt, with optional Shift; letters, digits, Space, F1–F11.',style='Card.TLabel',wraplength=560).pack(anchor='w',pady=(8,0))
        ttk.Label(settings, text='The shared switch applies immediately. Apply saves only the selected action.',
                  style='Card.Muted.TLabel', wraplength=560).pack(anchor='w', pady=(6, 0))
        ttk.Label(settings, textvariable=self.shortcut_feedback,
                  style='Card.TLabel', wraplength=560).pack(anchor='w', pady=(6, 0))
        integration=self._card(content,'System integration')
        ttk.Checkbutton(integration,text='Start when signing in to Windows',variable=self.autostart,command=self._toggle_startup).pack(anchor='w',pady=4)
        self.path_button=ttk.Button(integration,text='Add to PATH',command=self._add_path)
        self.path_button.pack(anchor='w',pady=6)
        ttk.Label(integration,textvariable=self.status,style='Card.TLabel',wraplength=560).pack(anchor='w')
        footer=ttk.Frame(self.root,padding=(pad,12))
        footer.pack(fill='x')
        ttk.Button(footer,text='Exit',command=self.shutdown).pack(side='right')
        ttk.Button(footer,text='Hide to tray',command=self._hide).pack(side='right',padx=8)

    def _card(self, parent, title):
        """Create one consistently spaced surface without extra image assets."""
        card=ttk.Frame(parent,style='Card.TFrame',padding=round(16*self._scale))
        card.pack(fill='x',pady=(0,12))
        ttk.Label(card,text=title,style='Card.TLabel',font=self.fonts['section']).pack(anchor='w',pady=(0,4))
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
            width=min(round(720*self._scale),right-left-32)
            height=min(round(620*self._scale),bottom-top-48)
            self.root.minsize(min(width,round(640*self._scale)),min(height,round(520*self._scale)))
            self.root.geometry(f'{width}x{height}+{left+16}+{top+16}')
        except Exception:
            self.root.minsize(min(640,self.root.winfo_screenwidth()),min(520,self.root.winfo_screenheight()))

    def _choose(self):
        """Preview the explicitly selected local file."""
        path=filedialog.askopenfilename(parent=self.root)
        if path:
            self.open(path)

    def _choose_for_diff(self):
        """Choose a tracked text file for a working-tree versus HEAD comparison."""
        self.diff_status.set('Choose a file in the file picker…')
        path = filedialog.askopenfilename(parent=self.root)
        if path:
            self.diff_status.set(f'Selected: {Path(path).name}. Comparing…')
            self._start_comparison(path)
        else:
            self.diff_status.set('Git comparison cancelled.')

    def _start_comparison(self, path):
        """Run Git comparison away from the Tk thread."""
        if self._diff_thread and self._diff_thread.is_alive():
            return
        from offlook.core.git_diff import compare_with_head
        self.diff_status.set('Comparing the working file with Git HEAD…')
        def work():
            try:
                self._diff_results.put((compare_with_head(path), None))
            except OffLookError as exc:
                self._diff_results.put((None, str(exc)))
            except Exception as exc:
                self._diff_results.put((None, f'Git comparison failed: {type(exc).__name__}: {exc}'))
        self._diff_thread = threading.Thread(target=work, name='OffLookGitDiff', daemon=True)
        self._diff_thread.start()

    def _choose_search_folder(self):
        """Choose the root folder for recursive local search."""
        folder = filedialog.askdirectory(parent=self.root)
        if folder:
            self.search_folder.set(folder)
            self.search_status.set('Ready to search.')

    def _search(self):
        """Run recursive search off the Tk thread and display bounded results."""
        if self._search_thread and self._search_thread.is_alive():
            return
        folder = self.search_folder.get().strip()
        if not folder:
            self.search_status.set('Choose a folder first.')
            return
        from offlook.core import FileKind, find_files
        kinds = {'Text': FileKind.TEXT, 'Markdown': FileKind.MARKDOWN, 'Code': FileKind.CODE,
                 'CSV': FileKind.CSV, 'Images': FileKind.IMAGE, 'PDF': FileKind.PDF,
                 'Documents (.doc/.xlsx)': FileKind.DOCUMENT,
                 'Other / unknown': FileKind.BINARY}
        selected_kind = kinds.get(self.search_kind.get())
        self.search_button.state(['disabled'])
        self.search_status.set('Searching…')
        self._search_thread = threading.Thread(
            target=self._search_worker,
            args=(folder, self.search_name.get(), selected_kind, find_files),
            name='OffLookSearch', daemon=True,
        )
        self._search_thread.start()

    def _search_worker(self, folder, filename, kind, finder):
        """Return search results without touching Tk from the worker thread."""
        try:
            self._search_results.put((finder(folder, filename=filename, kind=kind), None))
        except OffLookError as exc:
            self._search_results.put((None, str(exc)))
        except OSError as exc:
            self._search_results.put((None, f'File search failed: {exc}'))

    def _open_search_result(self, _event):
        """Preview the selected search result."""
        selected = self.search_tree.selection()
        if selected:
            self.open(self.search_tree.item(selected[0], 'values')[1])

    def _choose_convert_files(self):
        """Choose one or more files manually and show the conversion wheel."""
        paths = filedialog.askopenfilenames(parent=self.root)
        if paths:
            self._show_conversion_wheel(paths)

    def _show_conversion_wheel(self, paths):
        """Offer every reachable target format for the selected files."""
        from offlook.core import format_label, reachable_targets
        from offlook.ui.convert_wheel import show_conversion_wheel
        if self.convert_wheel is not None and self.convert_wheel.winfo_exists():
            self.convert_wheel.destroy()
        mode = self.convert_mode.get().strip() or 'auto'
        targets = reachable_targets(paths, mode)
        if not targets:
            self.convert_status.set('No conversion is available for the selected files.')
            self.status.set('No conversion is available for the selected files.')
            return
        options = [(extension, format_label(extension)) for extension in targets]
        self._convert_paths = tuple(Path(path) for path in paths)
        self._show()
        self.convert_wheel = show_conversion_wheel(self.root, options, self._start_conversion)

    def _start_conversion(self, target):
        """Run file conversion away from the Tk thread and report the outcome."""
        if self._convert_thread and self._convert_thread.is_alive():
            self.convert_status.set('A conversion is already running.')
            return
        paths = self._convert_paths
        mode = self.convert_mode.get().strip() or 'auto'
        self.convert_status.set(f'Converting {len(paths)} file(s) to {target.lstrip(".").upper()}…')
        def work():
            try:
                from offlook.core import convert_files
                self._convert_results.put((convert_files(paths, target, mode=mode), None))
            except OffLookError as exc:
                self._convert_results.put((None, str(exc)))
            except Exception as exc:
                self._convert_results.put((None, f'Conversion failed: {type(exc).__name__}: {exc}'))
        self._convert_thread = threading.Thread(target=work, name='OffLookConvert', daemon=True)
        self._convert_thread.start()

    def _convert_mode_changed(self):
        """Persist the conversion fidelity mode when the user changes it."""
        try:
            desired = replace(self.context.config.current, convert_mode=self.convert_mode.get().strip() or 'auto')
            self.context.config.update(desired, persist=True)
        except OffLookError as exc:
            self.convert_mode.set(self.context.config.current.convert_mode)
            self.status.set(str(exc))

    def _choose_filter_folder(self):
        """Choose the root folder for format filtering."""
        folder = filedialog.askdirectory(parent=self.root)
        if folder:
            self.filter_folder.set(folder)
            self.filter_status.set('Ready to filter.')

    def _apply_filter(self):
        """Run multi-format filtering off the Tk thread."""
        if self._filter_thread and self._filter_thread.is_alive():
            return
        folder = self.filter_folder.get().strip()
        if not folder:
            self.filter_status.set('Choose a folder first.')
            return
        kinds = [kind for kind, variable in self.filter_vars.items() if variable.get()]
        from offlook.core import filter_files
        self.filter_button.state(['disabled'])
        self.filter_status.set('Filtering…')
        self._filter_thread = threading.Thread(
            target=self._filter_worker, args=(folder, kinds, filter_files),
            name='OffLookFilter', daemon=True,
        )
        self._filter_thread.start()

    def _filter_worker(self, folder, kinds, filterer):
        """Return filter results without touching Tk from the worker thread."""
        try:
            self._filter_results.put((filterer(folder, kinds=kinds), None))
        except OffLookError as exc:
            self._filter_results.put((None, str(exc)))
        except OSError as exc:
            self._filter_results.put((None, f'File filtering failed: {exc}'))

    def _open_filter_result(self, _event):
        """Preview the selected filtered file."""
        selected = self.filter_tree.selection()
        if selected:
            self.open(self.filter_tree.item(selected[0], 'values')[1])

    def _save_ai(self):
        """Persist AI settings only when they validate."""
        try:
            desired = replace(
                self.context.config.current,
                ai_enabled=self.ai_enabled.get(),
                ai_base_url=self.ai_base_url.get().strip(),
                ai_api_key=self.ai_key.get().strip(),
                ai_model=self.ai_model.get().strip(),
            )
            self.context.config.update(desired, persist=True)
            self.status.set('AI settings saved')
        except OffLookError as exc:
            self.status.set(str(exc))

    def _run_ai(self):
        """Run the configured AI assistant in a worker, never on the Tk thread."""
        if self._ai_thread and self._ai_thread.is_alive():
            return
        instruction = self.ai_instruction.get().strip()
        if not instruction:
            self.ai_status.set('Enter an instruction first.')
            return
        config = self.context.config.current
        if not config.ai_api_key:
            self.ai_status.set('Save an API key first.')
            return
        self.ai_run_button.state(['disabled'])
        self.ai_status.set('Running assistant…')
        def work():
            try:
                from offlook.core import OpenAiCompatibleProvider, run_instruction
                provider = OpenAiCompatibleProvider(config.ai_base_url, config.ai_api_key, config.ai_model)
                self._ai_results.put((run_instruction(instruction, provider=provider), None))
            except OffLookError as exc:
                self._ai_results.put((None, str(exc)))
            except Exception as exc:
                self._ai_results.put((None, f'AI assistant failed: {type(exc).__name__}: {exc}'))
        self._ai_thread = threading.Thread(target=work, name='OffLookAi', daemon=True)
        self._ai_thread.start()

    def _set_ai_output(self, value):
        """Replace the read-only assistant transcript."""
        self.ai_output.configure(state='normal')
        self.ai_output.delete('1.0', 'end')
        self.ai_output.insert('1.0', value)
        self.ai_output.configure(state='disabled')

    def _toggle_startup(self):
        """Change logon registration only on an explicit user action."""
        if self.startup is None:
            return
        requested=self.autostart.get()
        try:
            self.startup.set_enabled(requested)
            self.status.set('Start at sign-in enabled' if requested else 'Start at sign-in disabled')
        except OffLookError as exc:
            self.autostart.set(not requested)
            self.status.set(str(exc))

    def _hide(self):
        """Hide only when the tray provides a usable return route."""
        if self.tray is not None and not self.tray.is_stopped:
            self.root.withdraw()
        else:
            self.status.set('System tray unavailable. Use Exit to close OffLook.')

    def _show(self):
        """Restore the main controls without disrupting the preview."""
        self.root.deiconify()
        self.root.lift()

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
        for action, (field, _) in self.SHORTCUT_ACTIONS.items():
            configured = getattr(config, field)
            active = self.listeners.get(action)
            pending = self._pending_listeners.get(action)
            deferred = self._deferred_starts.get(action)
            error = self._hotkey_errors.get(action)
            if not config.hotkey_enabled or not self.resident or self.closing:
                text = 'Disabled'
            elif active is not None:
                text = active.combo
                if configured != active.combo:
                    text += f'; configured {configured} is not active'
                if pending is not None or deferred is not None:
                    target = pending.combo if pending is not None else deferred[0]
                    text += f'; Registering {target}…'
                if error:
                    text += f'; Unavailable ({error[0]}): {error[1]}'
            elif pending is not None or deferred is not None:
                target = pending.combo if pending is not None else deferred[0]
                text = f'Registering {target}…'
            else:
                reason = error[1] if error else 'not registered'
                text = f'Unavailable ({configured}): {reason}'
                if error and error[0] != configured:
                    text += f'; attempted {error[0]}'
            self.shortcut_statuses[action].set(text)
        self._settings_busy()
        if self.help_window is not None and self.help_window.winfo_exists():
            from offlook.ui.help import update_help_shortcuts
            update_help_shortcuts(self.help_window, shortcuts=self._shortcut_summary())

    def _select_action(self, _event=None):
        """Switch only the displayed draft, never a saved binding."""
        self._cancel_recording()
        self._drafts[self._selected_action] = self.combo.get()
        self._selected_action = next(action for action, (_, label) in self.SHORTCUT_ACTIONS.items()
                                     if label == self.action.get())
        self.combo.set(self._drafts[self._selected_action])

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
        self.shortcut_feedback.set('Press a key combination; Esc to cancel.')
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
        self.shortcut_feedback.set('Recorded. Click Apply to save the selected shortcut.')

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
            self.shortcut_feedback.set('Windows-reserved shortcuts are not supported')
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
        """Validate all three bindings before registration or persistence."""
        self._cancel_recording()
        action = self._selected_action
        field, label = self.SHORTCUT_ACTIONS[action]
        self._drafts[action] = self.combo.get()
        try:
            spec = parse_hotkey(self.combo.get())
            desired = replace(self.context.config.current, **{field: spec.canonical})
            self._drafts[action] = spec.canonical
            self.combo.set(spec.canonical)
            if not desired.hotkey_enabled or not self.resident:
                self._save_hotkey_config(desired)
                self._hotkey_errors.pop(action, None)
                self.shortcut_feedback.set(f'{label} shortcut saved. Global shortcuts are disabled.')
                self._refresh_hotkey_status()
            else:
                self._begin_hotkey(action, spec.canonical, persist=True)
        except OffLookError as exc:
            self.shortcut_feedback.set(f'{label}: {exc}')
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
        self.shortcut_feedback.set('Global shortcuts enabled; see each action’s availability.'
                                   if requested else 'Global shortcuts disabled.')
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
        label = self.SHORTCUT_ACTIONS[action][1]
        self._hotkey_errors[action] = (combo, message)
        self._feedback_action = action
        self.shortcut_feedback.set(f'{label}: {message}; shortcut settings were not applied.')

    def _begin_hotkey(self, action: str, combo: str, *, persist: bool) -> None:
        """Keep the old action working until its fresh candidate is ready and saved."""
        if self.closing or action in self._pending_listeners:
            return
        config = self.context.config.current
        field = self.SHORTCUT_ACTIONS[action][0]
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
                    self.shortcut_feedback.set(f'{self.SHORTCUT_ACTIONS[action][1]} shortcut is active.')
                    self._feedback_action = None
            except OffLookError as exc:
                self._hotkey_failed(action, combo, str(exc))
            self._refresh_hotkey_status()
            return
        for owner, listener in self.listeners.items():
            if owner != action and listener.combo == combo:
                self._hotkey_failed(action, combo,
                                    f'Already active for {self.SHORTCUT_ACTIONS[owner][1]}; use an unused combination first')
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
                self.shortcut_feedback.set(f'{self.SHORTCUT_ACTIONS[action][1]} shortcut applied.')
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
                    self.shortcut_feedback.set(f'{self.SHORTCUT_ACTIONS[action][1]}: {event["message"]}')
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

    def _add_path(self):
        """Run add-only user PATH registration away from the Tk thread."""
        if self._path_thread and self._path_thread.is_alive():
            return
        from offlook.platforms.windows_environment import add_offlook_to_user_path
        self.path_button.state(['disabled'])
        self.status.set('Updating user PATH…')
        def work():
            """Return native results through a queue without touching Tk."""
            try:
                self._path_results.put((add_offlook_to_user_path(),None))
            except Exception as exc:
                self._path_results.put((None,str(exc)))
        self._path_thread=threading.Thread(target=work,name='OffLookPath',daemon=True)
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
        self.preview.set_loading('Updating resolution…' if self._preview_opened else 'Loading…')
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
        for window in (self.help_window, self.diff_window):
            if window is not None and window.winfo_exists():
                owned.add(win32gui.GetAncestor(window.winfo_id(), 2))
        if hwnd in owned:
            if action == 'preview' and hwnd == preview_hwnd:
                self._hotkey(hwnd)
            return
        {'preview': self._hotkey, 'search': self._search_hotkey,
         'diff': self._diff_hotkey, 'convert': self._convert_hotkey}[action](hwnd)

    def _hotkey(self, hwnd):
        """Toggle this preview or resolve a foreground Shell file."""
        import win32gui
        if self.preview and hwnd == win32gui.GetAncestor(self.preview.window.winfo_id(), 2):
            self.close_preview()
            return
        self._begin_selection('preview', hwnd)

    def _search_hotkey(self, hwnd):
        """Prepare the selected Explorer folder without starting a search."""
        self._begin_selection('search', hwnd)

    def _diff_hotkey(self, hwnd):
        """Resolve the selected Explorer file for comparison with Git HEAD."""
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
                                            allow_folder=action == 'search',
                                            multiple=action == 'convert'))

    def _cancel_selection(self, *, resume=True):
        if self.selection_hwnd is not None or self.selection_mode is not None:
            self.generation += 1
            self.runner.cancel()
            self.selection_hwnd = self.selection_mode = None
            if resume and self.preview is not None:
                self.preview.set_render_suspended(False)

    def _selection_feedback(self, action, message):
        label = self.SHORTCUT_ACTIONS[action][1]
        if action == 'search':
            self.search_status.set(f'{label}: {message}')
        elif action == 'diff':
            self.diff_status.set(f'{label}: {message}')
        else:
            self.status.set(f'{label}: {message}')

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
                self._selection_feedback(action, 'Foreground focus changed; selection cancelled.')
            elif action == 'convert':
                if result['data'].paths:
                    self._show_conversion_wheel(result['data'].paths)
                else:
                    self._selection_feedback(action, result['data'].reason or 'No local files selected')
            elif result['data'].path is None:
                self._selection_feedback(action, result['data'].reason)
            elif action == 'search':
                self.search_folder.set(str(result['data'].path))
                self.search_status.set('Folder selected from File Explorer. Enter a filename or choose a type, then click Search.')
                self._show()
                self.root.after_idle(self._focus_search)
            elif action == 'diff':
                self._start_comparison(result['data'].path)
            else:
                self.open(result['data'].path)
        finally:
            if self.preview is not None and self.preview is previous_preview:
                self.preview.set_render_suspended(False)

    def _scroll_into_view(self, widget: tk.Misc) -> None:
        """Bring the card's leading controls into the existing narrow scroll area."""
        self.main_canvas.update_idletasks()
        height = max(1, self.main_content.winfo_height())
        top = widget.winfo_rooty() - self.main_content.winfo_rooty()
        self.main_canvas.yview_moveto(max(0, top) / height)

    def _focus_search(self):
        if not self.closing:
            self._scroll_into_view(self.search_card)
            self.search_entry.focus_set()
            self.search_entry.selection_range(0, 'end')

    def _convert_hotkey(self, hwnd):
        """Collect every selected Explorer file for the conversion wheel."""
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
            result,error=self._path_results.get_nowait()
        except queue.Empty:
            pass
        else:
            self.path_button.state(['!disabled'])
            if error: self.status.set(error)
            else:
                message=f"{'Added to' if result.changed else 'Already in'} PATH: {result.scripts_dir}. Reopen PowerShell / Windows Terminal."
                if not result.broadcast_ok: message+=' Environment update notification failed.'
                if result.conflicting_executable: message+=f' Another version takes precedence: {result.conflicting_executable}; use py -m offlook.'
                self.status.set(message)
        try:
            search_results, search_error = self._search_results.get_nowait()
        except queue.Empty:
            pass
        else:
            if not self.closing:
                self.search_button.state(['!disabled'])
                for item in self.search_tree.get_children():
                    self.search_tree.delete(item)
                if search_error:
                    self.search_status.set(search_error)
                else:
                    for item in search_results:
                        self.search_tree.insert('', 'end', values=(item.kind.value, str(item.path)))
                    self.search_status.set(f'{len(search_results)} file(s) found.')
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
                self.diff_window = show_diff(self.root, comparison)
                self.diff_status.set(
                    'Differences found.' if comparison.changed else 'No differences from Git HEAD.'
                )
                self.status.set('Git comparison ready')
        try:
            filter_results, filter_error = self._filter_results.get_nowait()
        except queue.Empty:
            pass
        else:
            self.filter_button.state(['!disabled'])
            for item in self.filter_tree.get_children():
                self.filter_tree.delete(item)
            if filter_error:
                self.filter_status.set(filter_error)
            else:
                for item in filter_results:
                    self.filter_tree.insert('', 'end', values=(item.kind.value, str(item.path)))
                self.filter_status.set(f'{len(filter_results)} file(s) match the selected formats.')
        try:
            conversion, convert_error = self._convert_results.get_nowait()
        except queue.Empty:
            pass
        else:
            if convert_error:
                self.convert_status.set(convert_error)
                self.status.set(convert_error)
            else:
                outputs = sum(len(outcome.outputs) for outcome in conversion)
                message = f'Converted {len(conversion)} file(s) → {outputs} output file(s).'
                self.convert_status.set(message)
                self.status.set(message)
        try:
            ai_result, ai_error = self._ai_results.get_nowait()
        except queue.Empty:
            pass
        else:
            self.ai_run_button.state(['!disabled'])
            if ai_error:
                self.ai_status.set(ai_error)
                self._set_ai_output(ai_error)
            else:
                lines = [ai_result.answer]
                if ai_result.steps:
                    lines.append('')
                    lines.append('— Tool actions —')
                    for step in ai_result.steps:
                        lines.append(f'• {step.name}({step.arguments})')
                        if step.error:
                            lines.append(f'  error: {step.error}')
                self.ai_status.set('Assistant finished.')
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
        if self.closing and self.runner.is_closed and not listeners and (self.tray is None or self.tray.is_stopped) and (self._path_thread is None or not self._path_thread.is_alive()) and (self._search_thread is None or not self._search_thread.is_alive()) and (self._diff_thread is None or not self._diff_thread.is_alive()) and (self._filter_thread is None or not self._filter_thread.is_alive()) and (self._convert_thread is None or not self._convert_thread.is_alive()) and (self._ai_thread is None or not self._ai_thread.is_alive()):
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
        self.preview.destroy()
        self.preview = None
        self.context.events.publish('preview.closed', {'path': self.path})
        if not self.resident and exiting:
            self.shutdown()

    def shutdown(self):
        """Keep polling until every native listener and initiated PATH write is closed."""
        if self.closing: return
        self.closing=True
        self._cancel_recording()
        self._cancel_selection(resume=False)
        self.close_preview(exiting=False)
        self.unsubscribe()
        self.runner.close()
        self._stop_hotkeys()
        self._refresh_hotkey_status()
        if self.tray: self.tray.stop()
        if self.convert_wheel and self.convert_wheel.winfo_exists(): self.convert_wheel.destroy()
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
