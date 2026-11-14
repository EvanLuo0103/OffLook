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
        self.listener = self._pending_listener = self.search_listener = self._pending_search_listener = None
        self._pending_config = None
        self._pending_persist = False
        self._retiring_listeners = []
        self._hotkey_transaction_active = False
        self._recording = False
        self._record_target = 'preview'
        self._record_original = ''
        self._path_thread = None
        self._path_results = queue.Queue()
        self._search_thread = None
        self._search_results = queue.Queue()
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
        self.search_hotkey_status = tk.StringVar(value='Search shortcut starting…')
        self.combo = tk.StringVar(value=context.config.current.hotkey)
        self.search_combo = tk.StringVar(value=context.config.current.search_hotkey)
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
            self._configure_search_hotkey()
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
        search_shortcut_row = ttk.Frame(settings, style='Card.TFrame')
        search_shortcut_row.pack(fill='x', pady=(12, 0))
        ttk.Label(search_shortcut_row, text='Search shortcut:', style='Card.TLabel').pack(side='left')
        self.search_combo_entry = ttk.Entry(search_shortcut_row, textvariable=self.search_combo, state='readonly')
        self.search_combo_entry.pack(side='left', fill='x', expand=True, padx=8)
        self.search_record_button = ttk.Button(search_shortcut_row, text='Record', command=self._record_search)
        self.search_record_button.pack(side='left')
        self.search_apply_button = ttk.Button(search_shortcut_row, text='Apply', command=self._apply_search_hotkey)
        self.search_apply_button.pack(side='left', padx=(8, 0))
        self.search_combo_entry.bind('<KeyPress>', self._capture)
        ttk.Label(settings, textvariable=self.search_hotkey_status, style='Card.Muted.TLabel',
                  wraplength=560).pack(anchor='w', pady=(4, 0))
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
        self._record_target = 'preview'
        self._recording=True
        self.status.set('Press a key combination; Esc to cancel.')
        self.combo_entry.focus_set()

    def _record_search(self):
        """Begin recording the separate Explorer search shortcut."""
        self._record_original = self.search_combo.get()
        self._record_target = 'search'
        self._recording = True
        self.status.set('Press a search shortcut; Esc to cancel.')
        self.search_combo_entry.focus_set()

    def _capture(self,event):
        """Normalize a complete keyboard chord and leave it as an unsaved draft."""
        if not self._recording:
            return
        if event.keysym=='Escape':
            (self.search_combo if self._record_target == 'search' else self.combo).set(self._record_original)
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
            target = self.search_combo if self._record_target == 'search' else self.combo
            target.set(parse_hotkey('+'.join(tokens+[key])).canonical)
            self._recording=False
            self.status.set('Recorded. Click Apply to activate.')
        except OffLookError as exc:
            self.status.set(str(exc))
        return 'break'

    def _settings_busy(self,busy):
        """Prevent overlapping shortcut transactions."""
        for widget in (self.enable_control,self.record_button,self.apply_button,self.reset_button,
                       self.search_record_button,self.search_apply_button):
            widget.state(['disabled'] if busy else ['!disabled'])

    def _apply_hotkey(self):
        """Validate the draft; persistence happens only after candidate registration."""
        try:
            spec=parse_hotkey(self.combo.get())
            desired=replace(self.context.config.current,hotkey=spec.canonical,hotkey_enabled=self.enabled.get())
            self._begin_hotkey(desired,persist=True)
        except OffLookError as exc:
            self.status.set(str(exc))

    def _apply_search_hotkey(self):
        """Validate and register the separate Explorer search shortcut."""
        try:
            desired = replace(self.context.config.current, search_hotkey=parse_hotkey(self.search_combo.get()).canonical)
            self._begin_search_hotkey(desired, persist=True)
        except OffLookError as exc:
            self.status.set(str(exc))

    def _configure_hotkey(self):
        """Honor an externally changed config without writing it a second time."""
        self._begin_hotkey(self.context.config.current,persist=False)

    def _configure_search_hotkey(self):
        """Honor an externally changed search shortcut without writing it again."""
        self._begin_search_hotkey(self.context.config.current, persist=False)

    def _config_changed(self,event):
        """Avoid recursive registration from synchronous config.changed callbacks."""
        if self.resident and not self._hotkey_transaction_active:
            self._configure_hotkey()
            self._configure_search_hotkey()

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
        if self.resident and self.search_listener is None and self._pending_search_listener is None:
            self._configure_search_hotkey()

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
        except OffLookError as exc:
            self._retire(self._pending_listener)
            self.status.set(str(exc))
        finally:
            self._finish_hotkey()

    def _begin_search_hotkey(self, desired, *, persist):
        """Register the separate global shortcut used to open folder search."""
        if self._hotkey_transaction_active or self.closing:
            return
        active = self.search_listener
        if active is not None and not active.is_stopped and active.combo == desired.search_hotkey:
            return
        self._hotkey_transaction_active = True
        self._settings_busy(True)
        self._pending_config = desired
        self._pending_persist = persist
        from offlook.platforms.windows_hotkey import HotkeyListener
        self._pending_search_listener = HotkeyListener(desired.search_hotkey)
        self._pending_search_listener.start()

    def _commit_search_hotkey(self):
        """Persist a tested search shortcut before replacing the old listener."""
        try:
            if self._pending_persist:
                self.context.config.update(self._pending_config, persist=True)
            self._retire(self.search_listener)
            self.search_listener = self._pending_search_listener
            self.search_hotkey_status.set(f'Search shortcut ready: {self.search_listener.combo}')
            self.status.set(f'Search shortcut applied: {self.search_listener.combo}')
        except OffLookError as exc:
            self._retire(self._pending_search_listener)
            self.status.set(str(exc))
        finally:
            self._pending_search_listener = self._pending_config = None
            self._pending_persist = False
            self._hotkey_transaction_active = False
            self._settings_busy(False)
            self.search_combo.set(self.context.config.current.search_hotkey)

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
        """Resolve the selected Explorer file and open its parent folder in Search files."""
        import win32gui
        if self._recording and hwnd == win32gui.GetAncestor(self.root.winfo_id(), 2):
            self.search_combo.set(self.search_listener.combo)
            self._recording = False
            self.status.set('Search shortcut recorded. Click Apply to activate.')
            return
        if not hwnd or self.closing:
            return
        from offlook.platforms.windows_selection import SelectionRequest
        self.generation += 1
        self.selection_hwnd = hwnd
        self.selection_mode = 'search'
        self.search_hotkey_status.set('Search shortcut pressed; reading the selected Explorer file…')
        self.runner.submit(SelectionRequest(self.generation, hwnd, self.context.config.current))

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
                    self.search_hotkey_status.set(event['message'])
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
        pending_search = self._pending_search_listener
        if pending_search and not self.closing:
            for event in pending_search.poll():
                if self._pending_search_listener is not pending_search:
                    break
                if event['type'] == 'ready':
                    self._commit_search_hotkey()
                elif event['type'] == 'error':
                    self.status.set(f"{event['message']}; search shortcut not changed")
                    self._retire(pending_search)
                    self._pending_search_listener = self._pending_config = None
                    self._hotkey_transaction_active = False
                    self._settings_busy(False)
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
        for result in self.runner.poll():
            # Every resize/page/file switch invalidates older response generations.
            if self.closing or result['request_id']!=self.generation: continue
            if self.selection_hwnd is not None:
                import win32gui
                hwnd=self.selection_hwnd
                self.selection_hwnd=None
                if result['code']:
                    self.status.set(result['message'])
                    if self.selection_mode == 'search':
                        self.search_hotkey_status.set(result['message'])
                elif win32gui.GetForegroundWindow()==hwnd and result['data'].path is not None:
                    if self.selection_mode == 'search':
                        self.search_folder.set(str(result['data'].path.parent))
                        self.search_status.set('Folder selected from File Explorer. Enter a filename or choose a type, then click Search.')
                        self._show()
                        self._focus_search()
                    else:
                        self.open(result['data'].path)
                self.selection_mode = None
                if self.preview: self.preview.set_render_suspended(False)
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
        listeners=[item for item in [self.listener,self._pending_listener,self.search_listener,self._pending_search_listener,*self._retiring_listeners] if item]
        if self.closing and self.runner.is_closed and all(item.is_stopped for item in listeners) and (self.tray is None or self.tray.is_stopped) and (self._path_thread is None or not self._path_thread.is_alive()) and (self._search_thread is None or not self._search_thread.is_alive()):
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
        for listener in [self.listener,self._pending_listener,self.search_listener,self._pending_search_listener,*self._retiring_listeners]:
            if listener: listener.stop()
        if self.tray: self.tray.stop()
        if self.help_window and self.help_window.winfo_exists(): self.help_window.destroy()

    def run(self)->int:
        """Run the sole Tk loop and return the preview/interrupt exit code."""
        try:
            self.root.mainloop()
        except KeyboardInterrupt:
            self.exit_code=130
            self.shutdown()
            self.root.mainloop()
        return self.exit_code
