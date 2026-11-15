"""Main-thread application coordinator; parsing and native services stay off Tk."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog, ttk

from offlook.core.errors import OffLookError
from offlook.core.hotkeys import parse_hotkey
from offlook.preview.models import RenderRequest
from offlook.preview.worker import WorkerRunner
from offlook.ui.theme import COLORS


class PreviewApplication:
    """Coordinate one main window, one preview, and transactional native settings."""

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
        self.listener = self._pending_listener = self.search_listener = None
        self.diff_listener = None
        self._pending_config = None
        self._pending_persist = False
        self._retiring_listeners = []
        self._hotkey_transaction_active = False
        self._recording = False
        self._record_original = ''
        self._recording_convert = False
        self._convert_original = ''
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
        self.convert_listener = None
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
        self.hotkey_status = tk.StringVar(value='Shortcut not enabled')
        self.combo = tk.StringVar(value=context.config.current.hotkey)
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
            self._configure_hotkey()
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
        content.bind('<Configure>', lambda event: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>', lambda event: canvas.itemconfigure(item,width=event.width))
        primary = self._card(content, 'Quick preview')
        ttk.Button(primary, text='Choose file', style='Accent.TButton', command=self._choose).pack(anchor='w',pady=8)
        ttk.Label(primary, textvariable=self.hotkey_status, style='Card.TLabel', wraplength=560).pack(anchor='w')
        comparison = self._card(content, 'Git comparison')
        ttk.Button(comparison, text='Compare with Git HEAD', command=self._choose_for_diff).pack(anchor='w', pady=8)
        ttk.Label(comparison, text='Shortcut: Ctrl+Alt+D in File Explorer on a tracked text file.',
                  style='Card.Muted.TLabel', wraplength=560).pack(anchor='w')
        self.diff_status = tk.StringVar(value='Select a tracked text file to compare with Git HEAD.')
        ttk.Label(comparison, textvariable=self.diff_status, style='Card.Muted.TLabel',
                  wraplength=560).pack(anchor='w', pady=(6, 0))
        conversion = self._card(content, 'Convert files')
        ttk.Button(conversion, text='Choose files to convert', command=self._choose_convert_files).pack(anchor='w', pady=8)
        ttk.Label(conversion, text='Shortcut: Alt+C in File Explorer on one or more selected files.',
                  style='Card.Muted.TLabel', wraplength=560).pack(anchor='w')
        self.convert_status = tk.StringVar(value='Select files, then pick a target format from the wheel.')
        ttk.Label(conversion, textvariable=self.convert_status, style='Card.Muted.TLabel',
                  wraplength=560).pack(anchor='w', pady=(6, 0))
        search = self._card(content, 'Search files')
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
        ttk.Label(search, text='Explorer shortcut: select a folder and press Ctrl+Q.',
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
        self.enable_control = ttk.Checkbutton(settings,text='Enable global shortcut',variable=self.enabled)
        self.enable_control.pack(anchor='w',pady=4)
        self.combo_entry = ttk.Entry(settings,textvariable=self.combo,state='readonly',font=self.fonts['body'])
        self.combo_entry.pack(fill='x',pady=6)
        self.combo_entry.bind('<KeyPress>', self._capture)
        row=ttk.Frame(settings,style='Card.TFrame')
        row.pack(fill='x')
        self.record_button=ttk.Button(row,text='Record shortcut',command=self._record)
        self.apply_button=ttk.Button(row,text='Apply',command=self._apply_hotkey)
        self.reset_button=ttk.Button(row,text='Reset default',command=lambda:self.combo.set('Ctrl+Space'))
        for button in (self.record_button,self.apply_button,self.reset_button):
            button.pack(side='left',padx=(0,8))
        ttk.Label(settings,text='Ctrl or Alt, with optional Shift; letters, digits, Space, F1–F11.',style='Card.TLabel',wraplength=560).pack(anchor='w',pady=(8,0))
        ttk.Separator(settings, orient='horizontal').pack(fill='x', pady=12)
        ttk.Label(settings,text='Convert shortcut (files → format wheel)',style='Card.TLabel').pack(anchor='w')
        self.convert_combo = tk.StringVar(value=self.context.config.current.convert_hotkey)
        self.convert_entry = ttk.Entry(settings,textvariable=self.convert_combo,state='readonly',font=self.fonts['body'])
        self.convert_entry.pack(fill='x',pady=6)
        self.convert_entry.bind('<KeyPress>', self._capture_convert)
        convert_row=ttk.Frame(settings,style='Card.TFrame')
        convert_row.pack(fill='x')
        self.convert_record_button=ttk.Button(convert_row,text='Record',command=self._record_convert)
        self.convert_apply_button=ttk.Button(convert_row,text='Apply',command=self._apply_convert)
        self.convert_reset_button=ttk.Button(convert_row,text='Reset default',command=lambda:self.convert_combo.set('Alt+C'))
        for button in (self.convert_record_button,self.convert_apply_button,self.convert_reset_button):
            button.pack(side='left',padx=(0,8))
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
        self.status.set('Comparing the working file with Git HEAD…')
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
        targets = reachable_targets(paths)
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
        self.convert_status.set(f'Converting {len(paths)} file(s) to {target.lstrip(".").upper()}…')
        def work():
            try:
                from offlook.core import convert_files
                self._convert_results.put((convert_files(paths, target), None))
            except OffLookError as exc:
                self._convert_results.put((None, str(exc)))
            except Exception as exc:
                self._convert_results.put((None, f'Conversion failed: {type(exc).__name__}: {exc}'))
        self._convert_thread = threading.Thread(target=work, name='OffLookConvert', daemon=True)
        self._convert_thread.start()

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

    def _record_convert(self):
        """Capture a new conversion shortcut draft."""
        self._convert_original = self.convert_combo.get()
        self._recording_convert = True
        self.status.set('Press a key combination for conversion; Esc to cancel.')
        self.convert_entry.focus_set()

    def _capture_convert(self, event):
        """Normalize a conversion shortcut chord and leave it as an unsaved draft."""
        if not self._recording_convert:
            return
        if event.keysym == 'Escape':
            self.convert_combo.set(self._convert_original)
            self._recording_convert = False
            return 'break'
        if event.keysym in ('Control_L', 'Control_R', 'Alt_L', 'Alt_R', 'Shift_L', 'Shift_R'):
            return 'break'
        import win32api
        if win32api.GetAsyncKeyState(0x5B) & 0x8000 or win32api.GetAsyncKeyState(0x5C) & 0x8000:
            self.status.set('Windows-reserved shortcuts are not supported')
            return 'break'
        tokens = []
        if event.state & 4: tokens.append('Ctrl')
        if event.state & (8 | 0x20000): tokens.append('Alt')
        if event.state & 1: tokens.append('Shift')
        key = 'Space' if event.keysym == 'space' else event.keysym
        try:
            self.convert_combo.set(parse_hotkey('+'.join(tokens + [key])).canonical)
            self._recording_convert = False
            self.status.set('Recorded. Click Apply to activate.')
        except OffLookError as exc:
            self.status.set(str(exc))
        return 'break'

    def _apply_convert(self):
        """Persist the conversion shortcut and swap the active listener."""
        try:
            spec = parse_hotkey(self.convert_combo.get())
            desired = replace(self.context.config.current, convert_hotkey=spec.canonical)
            self.context.config.update(desired, persist=True)
            self._restart_convert_listener()
            self.status.set('Convert shortcut applied')
        except OffLookError as exc:
            self.status.set(str(exc))

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
        """Keep exactly one locally rendered help window with the active shortcut."""
        from offlook.ui.help import show_help
        if self.help_window is not None and self.help_window.winfo_exists():
            self.help_window.destroy()
        combo=self.listener.combo if self.listener is not None else 'Disabled'
        self.help_window=show_help(self.root,hotkey=combo)

    def _record(self):
        """Capture only focused Tk key events, never install a global keyboard hook."""
        self._record_original=self.combo.get()
        self._recording=True
        self.status.set('Press a key combination; Esc to cancel.')
        self.combo_entry.focus_set()

    def _capture(self,event):
        """Normalize a complete keyboard chord and leave it as an unsaved draft."""
        if not self._recording:
            return
        if event.keysym=='Escape':
            self.combo.set(self._record_original)
            self._recording=False
            return 'break'
        if event.keysym in ('Control_L','Control_R','Alt_L','Alt_R','Shift_L','Shift_R'):
            return 'break'
        import win32api
        if win32api.GetAsyncKeyState(0x5B)&0x8000 or win32api.GetAsyncKeyState(0x5C)&0x8000:
            self.status.set('Windows-reserved shortcuts are not supported')
            return 'break'
        tokens=[]
        if event.state&4: tokens.append('Ctrl')
        if event.state&(8|0x20000): tokens.append('Alt')
        if event.state&1: tokens.append('Shift')
        key='Space' if event.keysym=='space' else event.keysym
        try:
            self.combo.set(parse_hotkey('+'.join(tokens+[key])).canonical)
            self._recording=False
            self.status.set('Recorded. Click Apply to activate.')
        except OffLookError as exc:
            self.status.set(str(exc))
        return 'break'

    def _settings_busy(self,busy):
        """Prevent overlapping shortcut transactions."""
        for widget in (self.enable_control,self.record_button,self.apply_button,self.reset_button):
            widget.state(['disabled'] if busy else ['!disabled'])

    def _apply_hotkey(self):
        """Validate the draft; persistence happens only after candidate registration."""
        try:
            spec=parse_hotkey(self.combo.get())
            desired=replace(self.context.config.current,hotkey=spec.canonical,hotkey_enabled=self.enabled.get())
            self._begin_hotkey(desired,persist=True)
        except OffLookError as exc:
            self.status.set(str(exc))

    def _configure_hotkey(self):
        """Honor an externally changed config without writing it a second time."""
        self._begin_hotkey(self.context.config.current,persist=False)

    def _config_changed(self,event):
        """Avoid recursive registration from synchronous config.changed callbacks."""
        if self.resident and not self._hotkey_transaction_active:
            self._configure_hotkey()

    def _retire(self,listener):
        """Keep stopped listeners referenced until unregister errors are consumed."""
        if listener is not None:
            listener.stop()
            self._retiring_listeners.append(listener)

    def _begin_hotkey(self,desired,*,persist):
        """Keep the old listener working while a different combination is tested."""
        if self._hotkey_transaction_active or self.closing:
            return
        active=self.listener
        if desired.hotkey_enabled and active is not None and not active.is_stopped and active.combo==desired.hotkey:
            if persist and desired != self.context.config.current:
                self.context.config.update(desired,persist=True)
            return
        self._hotkey_transaction_active=True
        self._settings_busy(True)
        self._pending_config=desired
        self._pending_persist=persist
        if not desired.hotkey_enabled:
            self._commit_hotkey()
            return
        from offlook.platforms.windows_hotkey import HotkeyListener
        self._pending_listener=HotkeyListener(desired.hotkey)
        self._pending_listener.start()

    def _finish_hotkey(self):
        """Restore editable controls to the committed configuration."""
        self._pending_listener=self._pending_config=None
        self._hotkey_transaction_active=False
        self._settings_busy(False)
        self.combo.set(self.context.config.current.hotkey)
        self.enabled.set(self.context.config.current.hotkey_enabled)

    def _commit_hotkey(self):
        """Save before swapping; a failed save cannot disable the previous shortcut."""
        try:
            if self._pending_persist:
                self.context.config.update(self._pending_config,persist=True)
            old=self.listener
            self.listener=self._pending_listener
            self._retire(old)
            self.hotkey_status.set(f'Current shortcut: {self.listener.combo}' if self.listener else 'Global shortcut disabled')
            self.status.set('Shortcut settings applied')
            self._start_search_listener()
        except OffLookError as exc:
            self._retire(self._pending_listener)
            self.status.set(str(exc))
        finally:
            self._finish_hotkey()

    def _start_search_listener(self):
        """Start the fixed folder-search listener after preview registration succeeds."""
        if self.search_listener is not None or self.closing:
            return
        from offlook.platforms.windows_hotkey import HotkeyListener
        self.search_listener = HotkeyListener('Ctrl+Q')
        self.search_listener.start()

    def _start_diff_listener(self):
        """Start the fixed Explorer Git comparison shortcut after search registration."""
        if self.diff_listener is not None or self.closing:
            return
        from offlook.platforms.windows_hotkey import HotkeyListener
        self.diff_listener = HotkeyListener('Ctrl+Alt+D')
        self.diff_listener.start()

    def _start_convert_listener(self):
        """Start the configurable Explorer file-conversion shortcut."""
        if self.convert_listener is not None or self.closing:
            return
        from offlook.platforms.windows_hotkey import HotkeyListener
        self.convert_listener = HotkeyListener(self.context.config.current.convert_hotkey)
        self.convert_listener.start()

    def _restart_convert_listener(self):
        """Swap the conversion shortcut to the newly persisted combination."""
        if self.convert_listener is not None:
            self._retire(self.convert_listener)
            self.convert_listener = None
        if self.resident:
            self._start_convert_listener()

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
        if self.preview is not None:
            self.close_preview(exiting=False)
        from offlook.preview.window import PreviewWindow
        self.path=Path(path)
        self._preview_config=self.context.config.current
        self._preview_opened=False
        self.exit_code=0
        self.selection_hwnd=None
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

    def _hotkey(self,hwnd):
        """Resolve only foreground Shell files; ignore global keys during focused recording."""
        import win32gui
        if self._recording and hwnd==win32gui.GetAncestor(self.root.winfo_id(),2):
            self.combo.set(self.listener.combo)
            self._recording=False
            self.status.set('Recorded. Click Apply to activate.')
            return
        self._recording=False
        if self.preview and hwnd==win32gui.GetAncestor(self.preview.window.winfo_id(),2):
            self.close_preview()
            return
        if not hwnd or hwnd==win32gui.GetAncestor(self.root.winfo_id(),2): return
        from offlook.platforms.windows_selection import SelectionRequest
        if self.preview: self.preview.set_render_suspended(True)
        self.generation+=1
        self.selection_hwnd=hwnd
        self.selection_mode = 'preview'
        self.runner.submit(SelectionRequest(self.generation,hwnd,self.context.config.current))

    def _search_hotkey(self, hwnd):
        """Use Ctrl+Q to select the current Explorer folder for searching."""
        if not hwnd or self.closing:
            return
        from offlook.platforms.windows_selection import SelectionRequest
        self.generation += 1
        self.selection_hwnd = hwnd
        self.selection_mode = 'search'
        self.runner.submit(SelectionRequest(
            self.generation, hwnd, self.context.config.current, allow_folder=True
        ))

    def _diff_hotkey(self, hwnd):
        """Use Ctrl+Alt+D to compare the selected Explorer file with Git HEAD."""
        if not hwnd or self.closing:
            return
        from offlook.platforms.windows_selection import SelectionRequest
        self.generation += 1
        self.selection_hwnd = hwnd
        self.selection_mode = 'diff'
        self.runner.submit(SelectionRequest(self.generation, hwnd, self.context.config.current))

    def _convert_hotkey(self, hwnd):
        """Use the convert shortcut to collect every selected Explorer file."""
        if not hwnd or self.closing:
            return
        from offlook.platforms.windows_selection import SelectionRequest
        self.generation += 1
        self.selection_hwnd = hwnd
        self.selection_mode = 'convert'
        self.runner.submit(SelectionRequest(
            self.generation, hwnd, self.context.config.current, multiple=True
        ))

    def _poll(self):
        """Consume native events and worker results only on the owning Tk thread."""
        if self.tray:
            for event in self.tray.poll():
                if event=='exit': self.shutdown()
                elif event=='show' and not self.closing: self._show()
                elif event=='error' and not self.closing:
                    self._show()
                    self.status.set(self.tray.last_error)
        if self.listener:
            for event in self.listener.poll():
                if event['type']=='hotkey' and not self.closing: self._hotkey(event['foreground_hwnd'])
                elif event['type']=='error': self.hotkey_status.set(event['message'])
        if self.search_listener:
            for event in self.search_listener.poll():
                if event['type'] == 'hotkey' and not self.closing:
                    self._search_hotkey(event['foreground_hwnd'])
                elif event['type'] == 'error':
                    self.status.set(event['message'])
                elif event['type'] == 'ready':
                    self._start_diff_listener()
        if self.diff_listener:
            for event in self.diff_listener.poll():
                if event['type'] == 'hotkey' and not self.closing:
                    self._diff_hotkey(event['foreground_hwnd'])
                elif event['type'] == 'error':
                    self.status.set(event['message'])
                elif event['type'] == 'ready':
                    self._start_convert_listener()
        if self.convert_listener:
            for event in self.convert_listener.poll():
                if event['type'] == 'hotkey' and not self.closing:
                    self._convert_hotkey(event['foreground_hwnd'])
                elif event['type'] == 'error':
                    self.status.set(event['message'])
        pending=self._pending_listener
        if pending and not self.closing:
            for event in pending.poll():
                if self._pending_listener is not pending: break
                if event['type']=='ready': self._commit_hotkey()
                elif event['type']=='error':
                    active_text=self.listener.combo if self.listener else 'Disabled'
                    self.status.set(f"{event['message']}; settings not applied. Still using: {active_text}")
                    self._retire(pending)
                    self._finish_hotkey()
        for listener in self._retiring_listeners[:]:
            for event in listener.poll():
                if event['type']=='error': self.status.set(event['message'])
            if listener.is_stopped: self._retiring_listeners.remove(listener)
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
            if compare_error:
                self.diff_status.set(compare_error)
                self.status.set(compare_error)
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
                import win32gui
                hwnd=self.selection_hwnd
                self.selection_hwnd=None
                mode=self.selection_mode
                self.selection_mode = None
                if self.preview: self.preview.set_render_suspended(False)
                if result['code']:
                    self.status.set(result['message'])
                elif win32gui.GetForegroundWindow()!=hwnd:
                    pass
                elif mode == 'search' and result['data'].path is not None:
                    self.search_folder.set(str(result['data'].path))
                    self.search_status.set('Folder selected from File Explorer. Enter a filename or choose a type, then click Search.')
                    self._show()
                    self.search_entry.focus_set()
                    self.search_entry.selection_range(0, 'end')
                elif mode == 'diff' and result['data'].path is not None:
                    self._start_comparison(result['data'].path)
                elif mode == 'convert' and result['data'].paths:
                    self._show_conversion_wheel(result['data'].paths)
                elif result['data'].path is not None:
                    self.open(result['data'].path)
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
        listeners=[item for item in [self.listener,self._pending_listener,self.search_listener,self.diff_listener,self.convert_listener,*self._retiring_listeners] if item]
        if self.closing and self.runner.is_closed and all(item.is_stopped for item in listeners) and (self.tray is None or self.tray.is_stopped) and (self._path_thread is None or not self._path_thread.is_alive()) and (self._search_thread is None or not self._search_thread.is_alive()) and (self._diff_thread is None or not self._diff_thread.is_alive()) and (self._filter_thread is None or not self._filter_thread.is_alive()) and (self._convert_thread is None or not self._convert_thread.is_alive()) and (self._ai_thread is None or not self._ai_thread.is_alive()):
            self.root.destroy()
            return
        self.root.after(25,self._poll)

    def close_preview(self,exiting=True):
        """Cancel rendering before destroying its view and timers."""
        if self.preview is None: return
        self.generation+=1
        self.runner.cancel()
        self.preview.destroy()
        self.preview=None
        self.context.events.publish('preview.closed',{'path':self.path})
        if not self.resident and exiting: self.shutdown()

    def shutdown(self):
        """Keep polling until every native listener and initiated PATH write is closed."""
        if self.closing: return
        self.closing=True
        self.close_preview(exiting=False)
        self.unsubscribe()
        self.runner.close()
        for listener in [self.listener,self._pending_listener,self.search_listener,self.diff_listener,self.convert_listener,*self._retiring_listeners]:
            if listener: listener.stop()
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
