"""Deterministic native-boundary regressions using the real withdrawn Tk coordinator."""
from dataclasses import replace
from pathlib import Path
import sys
import tempfile
import threading
import time
import tkinter as tk
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from offlook.core import create_context, format_label
from offlook.core.errors import ConfigError, ConversionError, FileAccessError
from offlook.core.files import FileKind
from offlook.gui import PreviewApplication
from offlook.platforms.windows_selection import SelectionResult, _query_foreground
from offlook.ui.i18n import tr


class NativeListener:
    """Controlled OS boundary: production transaction logic and persistence stay real."""
    failures=set()
    batches={}
    instances=[]
    def __init__(self,combo):
        self.combo=combo;self.events=[];self.is_stopped=True
        self.instances.append(self)
    def start(self):
        self.is_stopped=False
        self.events.extend(self.batches.get(self.combo,[{'type':'error','combo':self.combo,'message':'occupied'}] if self.combo in self.failures else [{'type':'ready','combo':self.combo}]))
    def stop(self):self.is_stopped=True
    def poll(self):
        events,self.events=self.events,[]
        return events


@unittest.skipUnless(sys.platform=='win32','Windows GUI coordinator')
class ShortcutIntegrationTests(unittest.TestCase):
    """Catch consumer-visible partial startup and replacement/disable regressions."""
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path=Path(self.directory.name)/'config.json'
        self.path.write_text('{}',encoding='utf-8')
        NativeListener.failures=set();NativeListener.batches={};NativeListener.instances=[]
        self.patch=patch('offlook.platforms.windows_hotkey.HotkeyListener',NativeListener)
        self.patch.start();self.addCleanup(self.patch.stop)
        try:self.app=PreviewApplication(create_context(self.path),resident=False)
        except tk.TclError as exc:self.skipTest(str(exc))
        self.app.resident=True
        self.errors=[]
        self.app.root.report_callback_exception=lambda kind,value,tb:self.errors.append(value)
        self.addCleanup(self.close)
    def close(self):
        self.app.shutdown()
        end=time.monotonic()+3
        while time.monotonic()<end:
            try:
                self.app.root.update()
                if not self.app.root.winfo_exists():break
            except tk.TclError:break
            time.sleep(.01)
        self.assertEqual(self.errors,[])
    def wait_for(self,predicate):
        end=time.monotonic()+3
        while time.monotonic()<end:
            self.app.root.update()
            if predicate():return
            time.sleep(.01)
        self.fail('Coordinator did not reach expected state')
    def start(self):
        self.app._reconcile_hotkeys()
        self.wait_for(lambda: set(self.app.listeners) == set(self.app.SHORTCUT_ACTIONS))
    def test_search_failure_does_not_disable_preview_or_diff(self):
        NativeListener.failures={'Ctrl+Q'}
        self.app._reconcile_hotkeys()
        self.wait_for(lambda:set(self.app.listeners)=={'preview','diff','convert','filter'})
        self.assertEqual(self.app.listeners['diff'].combo,'Ctrl+Alt+D')
    def test_preview_failure_does_not_disable_other_actions(self):
        NativeListener.failures={'Ctrl+Space'}
        self.app._reconcile_hotkeys()
        self.wait_for(lambda:set(self.app.listeners)=={'search','diff','convert','filter'})
        self.assertEqual(self.app.listeners['search'].combo,'Ctrl+Q')
    def test_search_and_diff_replacements_preserve_other_bindings(self):
        self.start()
        old=self.app.listeners.copy()
        for action,field,combo in [('search','search_hotkey','Alt+Shift+S'),('diff','diff_hotkey','Alt+Shift+D')]:
            self.app._begin_hotkey(action,combo,persist=True)
            self.wait_for(lambda:self.app.listeners[action].combo==combo)
            self.assertEqual(getattr(create_context(self.path).config.current,field),combo)
            self.assertTrue(old[action].is_stopped)
        self.assertIs(self.app.listeners['preview'],old['preview'])
    def test_conflict_and_save_failure_keep_old_registration_and_file(self):
        self.start();self.app.context.config.update(self.app.context.config.current,persist=True)
        saved=self.path.read_bytes();old=self.app.listeners['search']
        NativeListener.failures={'Alt+Shift+S'}
        self.app._begin_hotkey('search','Alt+Shift+S',persist=True)
        self.wait_for(lambda:NativeListener.instances[-1].is_stopped)
        self.assertIs(self.app.listeners['search'],old);self.assertEqual(self.path.read_bytes(),saved)
        with patch.object(self.app.context.config,'_persist',side_effect=ConfigError('disk failure')):
            self.app._begin_hotkey('search','Alt+Shift+T',persist=True)
            self.wait_for(lambda:NativeListener.instances[-1].is_stopped)
        self.assertIs(self.app.listeners['search'],old);self.assertEqual(self.path.read_bytes(),saved)
    def test_error_in_ready_batch_never_promotes(self):
        self.start();old=self.app.listeners['diff']
        NativeListener.batches['Alt+Shift+D']=[{'type':'ready','combo':'Alt+Shift+D'},{'type':'error','combo':'Alt+Shift+D','message':'failed after ready'}]
        self.app._begin_hotkey('diff','Alt+Shift+D',persist=True)
        self.wait_for(lambda:NativeListener.instances[-1].is_stopped)
        self.assertIs(self.app.listeners['diff'],old)
        self.assertEqual(self.app.context.config.current.diff_hotkey,'Ctrl+Alt+D')
    def test_shared_disable_save_failure_preserves_all_keys(self):
        self.start();old=self.app.listeners.copy()
        self.app.enabled.set(False)
        with patch.object(self.app.context.config,'_persist',side_effect=ConfigError('disk failure')):
            self.app._set_hotkeys_enabled()
        self.assertEqual(self.app.listeners,old)
        self.assertTrue(self.app.enabled.get())
        self.app.enabled.set(False);self.app._set_hotkeys_enabled()
        self.wait_for(lambda:not self.app.listeners)
        self.assertTrue(all(listener.is_stopped for listener in old.values()))
        self.assertFalse(create_context(self.path).config.current.hotkey_enabled)
        self.app.enabled.set(True);self.app._set_hotkeys_enabled()
        self.wait_for(lambda: set(self.app.listeners) == set(self.app.SHORTCUT_ACTIONS))
    def test_selected_apply_drafts_and_duplicate_rejection(self):
        self.start()
        self.app.action.set(tr('action.search'));self.app._select_action()
        self.app.combo.set('Alt+Shift+S')
        self.app.action.set(tr('action.diff'));self.app._select_action()
        self.app.combo.set('Alt+Shift+D')
        self.app.action.set(tr('action.search'));self.app._select_action()
        self.assertEqual(self.app.combo.get(),'Alt+Shift+S')
        self.app.apply_button.invoke()
        self.wait_for(lambda:self.app.listeners['search'].combo=='Alt+Shift+S')
        self.app.action.set(tr('action.diff'));self.app._select_action()
        self.assertEqual(self.app.combo.get(),'Alt+Shift+D')
        self.app.combo.set('Alt+Shift+S');saved=self.path.read_bytes()
        self.app.apply_button.invoke()
        self.assertEqual(self.path.read_bytes(),saved)
        self.assertEqual(self.app.listeners['diff'].combo,'Ctrl+Alt+D')
    def test_external_change_invalidates_pending_user_edit(self):
        self.start()
        NativeListener.batches['Alt+Shift+S']=[]
        self.app._begin_hotkey('search','Alt+Shift+S',persist=True)
        stale=NativeListener.instances[-1]
        latest=replace(self.app.context.config.current,search_hotkey='Alt+Shift+T',always_on_top=True)
        self.app.context.config.update(latest)
        stale.events.append({'type':'ready','combo':stale.combo})
        self.wait_for(lambda:self.app.listeners['search'].combo=='Alt+Shift+T')
        self.assertTrue(stale.is_stopped)
        self.assertTrue(self.app.context.config.current.always_on_top)
        self.assertEqual(self.app.context.config.current.search_hotkey,'Alt+Shift+T')
    def test_registered_search_key_records_preview_draft(self):
        import win32gui
        self.start()
        self.app._record()
        hwnd=win32gui.GetAncestor(self.app.root.winfo_id(),2)
        with patch('win32gui.GetForegroundWindow',return_value=hwnd):
            self.app._dispatch_hotkey('search',hwnd,'Ctrl+Q')
        self.assertEqual(self.app.combo.get(),'Ctrl+Q')
        self.assertFalse(self.app._recording)
        self.assertIsNone(self.app.selection_hwnd)
    def test_candidate_and_retiring_keys_never_start_selection(self):
        self.start()
        old=self.app.listeners['search']
        NativeListener.batches['Alt+Shift+S']=[{'type':'ready','combo':'Alt+Shift+S'},
            {'type':'hotkey','combo':'Alt+Shift+S','foreground_hwnd':123}]
        self.app._begin_hotkey('search','Alt+Shift+S',persist=True)
        self.wait_for(lambda:self.app.listeners['search'].combo=='Alt+Shift+S')
        old.events.append({'type':'hotkey','combo':old.combo,'foreground_hwnd':123})
        self.app._poll_hotkeys()
        self.assertIsNone(self.app.selection_hwnd)
    def test_compare_hotkey_opens_sorted_result_from_multiselection(self):
        self.start()
        root = Path(self.directory.name)
        old, new = root / '01-old.md', root / '02-new.md'
        old.write_text('before\n', encoding='utf-8')
        new.write_text('after\n', encoding='utf-8')
        listener = self.app.listeners['diff']
        listener.events.append({'type': 'hotkey', 'combo': listener.combo, 'foreground_hwnd': 123})
        with patch('win32gui.GetForegroundWindow', return_value=123), patch.object(self.app.runner, 'submit') as submit:
            self.app._poll_hotkeys()
            request = submit.call_args.args[0]
            self.assertTrue(request.multiple and request.strict_pair)
            response = dict(request_id=request.request_id, code=None,
                            data=SelectionResult(None, '', (new, old)))
            with patch.object(self.app.runner, 'poll', side_effect=[[response]] + [[]] * 200):
                self.wait_for(lambda: self.app.diff_window is not None and self.app.diff_window.winfo_viewable())
        self.assertIn('01-old.md / 02-new.md', self.app.diff_window.title())
        self.assertTrue(self.app.diff_status.get() == tr('status.diff.differences'))

    def deliver_shell_selection(self, action, selection, ready):
        listener = self.app.listeners[action]
        listener.events.append({'type': 'hotkey', 'combo': listener.combo, 'foreground_hwnd': 123})
        with patch('win32gui.GetForegroundWindow', return_value=123), patch.object(self.app.runner, 'submit') as submit:
            self.app._poll_hotkeys()
            request = submit.call_args.args[0]
            response = dict(request_id=request.request_id, code=None, data=selection)
            with patch.object(self.app.runner, 'poll', side_effect=[[response]] + [[]] * 200):
                self.wait_for(ready)

    def conversion_is_visible(self):
        dialog = self.app.convert_dialog
        return dialog is not None and dialog.winfo_exists() and dialog.winfo_viewable()

    def test_convert_hotkey_keeps_root_hidden_and_shows_success_in_place(self):
        self.start()
        root = self.app.root
        maps = []
        root.bind('<Map>', lambda event: maps.append(event.widget) if event.widget is root else None, add='+')
        source = Path(self.directory.name) / 'note.md'
        source.write_text('# Hello\nworld', encoding='utf-8')
        self.deliver_shell_selection('convert', SelectionResult(None, '', (source,)), self.conversion_is_visible)
        dialog = self.app.convert_dialog
        original_id = dialog.winfo_id()
        dialog.dropdown.set(format_label('.txt'))
        dialog.convert_button.invoke()
        expected = tr('status.convert.done', n=1, m=1)
        self.wait_for(lambda: dialog.summary.cget('text') == expected)

        output = source.with_suffix('.txt')
        self.assertIn('world', output.read_text(encoding='utf-8'))
        self.assertIn(str(output), dialog.details.get('1.0', 'end'))
        self.assertIs(self.app.convert_dialog, dialog)
        self.assertEqual(dialog.winfo_id(), original_id)
        self.assertEqual([w for w in root.winfo_children() if isinstance(w, tk.Toplevel) and w.winfo_viewable()], [dialog])
        self.assertEqual(root.state(), 'withdrawn')
        self.assertEqual(maps, [])
        dialog.dismiss_button.invoke()
        self.assertFalse(dialog.winfo_exists())

    def test_conversion_failure_and_reentry_use_same_dialog(self):
        self.start()
        source = Path(self.directory.name) / 'note.md'
        source.write_text('hello', encoding='utf-8')
        self.deliver_shell_selection('convert', SelectionResult(None, '', (source,)), self.conversion_is_visible)
        dialog = self.app.convert_dialog
        original_id = dialog.winfo_id()
        ready, release = threading.Event(), threading.Event()
        expected = tr('status.convert.failed')

        def fail_conversion(*args, **kwargs):
            ready.set()
            if not release.wait(5):
                raise AssertionError('Test did not release conversion')
            raise ConversionError('fixture failure')

        with patch('offlook.core.convert_files', side_effect=fail_conversion) as convert:
            dialog.dropdown.set(format_label('.txt'))
            dialog.convert_button.invoke()
            try:
                self.wait_for(ready.is_set)
                self.assertTrue(dialog.convert_button.instate(['disabled']))
                self.assertTrue(dialog.dismiss_button.instate(['disabled']))
                dialog.event_generate('<Escape>')
                dialog.tk.call(dialog.protocol('WM_DELETE_WINDOW'))
                self.assertTrue(dialog.winfo_exists())
                listener = self.app.listeners['convert']
                listener.events.append({'type': 'hotkey', 'combo': listener.combo, 'foreground_hwnd': 123})
                with patch.object(self.app.runner, 'submit') as submit:
                    self.app._poll_hotkeys()
                    submit.assert_not_called()
                self.app._set_language('zh')
                self.assertIn('TXT', dialog.summary.cget('text'))
                self.assertEqual(dialog.winfo_id(), original_id)
                convert.assert_called_once()
            finally:
                release.set()
            self.wait_for(lambda: dialog.summary.cget('text') == expected)

        self.assertIs(self.app.convert_dialog, dialog)
        self.assertEqual(dialog.winfo_id(), original_id)
        self.assertEqual(dialog.details.get('1.0', 'end-1c'), 'fixture failure')
        self.assertEqual(self.app.root.state(), 'withdrawn')
        dialog.dismiss_button.invoke()
        self.assertFalse(dialog.winfo_exists())

        unsupported = source.with_name('unsupported.bin')
        unsupported.write_bytes(b'\x00\x01\x02')
        self.deliver_shell_selection('convert', SelectionResult(None, '', (unsupported,)), self.conversion_is_visible)
        replacement = self.app.convert_dialog
        self.assertEqual(replacement.summary.cget('text'), tr('status.convert.none'))
        self.assertFalse(replacement.dropdown.winfo_ismapped())
        self.assertFalse(replacement.convert_button.winfo_ismapped())
        self.assertEqual(self.app.root.state(), 'withdrawn')

    def test_search_shortcut_opens_search_page_and_keeps_results(self):
        self.start()
        folder = Path(self.directory.name)
        match = folder / 'needle.txt'
        match.write_text('match', encoding='utf-8')
        (folder / 'other.txt').write_text('other', encoding='utf-8')
        self.app._page_buttons['settings'].invoke()
        self.app.search_name.set('needle')
        self.app.search_kind_box.set(tr('kind.text'))
        self.deliver_shell_selection('search', SelectionResult(folder, ''), self.app.search_entry.winfo_viewable)

        def visible_pages():
            return [key for key, page in self.app._pages.items() if page.winfo_viewable()]

        self.assertEqual(visible_pages(), ['search'])
        self.assertEqual(self.app.search_folder.get(), str(folder))
        self.assertTrue(self.app.search_entry.selection_present())
        self.app.search_button.invoke()
        self.app._page_buttons['filter'].invoke()
        self.wait_for(lambda: self.app.search_status.get() == tr('status.search.found', n=1))
        self.assertEqual(visible_pages(), ['filter'])
        self.app._page_buttons['search'].invoke()
        self.app.root.update_idletasks()
        self.assertEqual(self.app.search_name.get(), 'needle')

        def result_paths():
            tree = self.app.search_tree
            return [tree.item(row, 'values')[1] for row in tree.get_children()]

        self.assertEqual(result_paths(), [str(match)])
        self.app._set_language('zh')
        self.app.root.update_idletasks()
        self.assertEqual(visible_pages(), ['search'])
        self.assertEqual(result_paths(), [str(match)])
        self.assertEqual(self.app.search_status.get(), tr('status.search.found', n=1))
        self.assertEqual(self.app.search_kind_box.get(), tr('kind.text'))
        self.assertEqual(self.app.search_button.cget('text'), tr('btn.search'))

    def test_standalone_filter_preview_and_close_keep_root_hidden(self):
        self.app.resident = False
        folder = Path(self.directory.name)
        match = folder / 'needle.txt'
        match.write_text('match', encoding='utf-8')
        (folder / 'other.md').write_text('# other', encoding='utf-8')
        root = self.app.root
        maps = []
        root.bind('<Map>', lambda event: maps.append(event.widget) if event.widget is root else None, add='+')

        self.app.open_filter(folder, kinds=(FileKind.TEXT,))
        dialog = self.app.filter_dialog
        self.wait_for(dialog.winfo_viewable)
        self.assertTrue(dialog.kind_vars[FileKind.TEXT].get())
        self.assertEqual(dialog.status.get(), tr('status.filter.ready'))
        self.assertFalse(dialog.tree.get_children())
        dialog.apply_button.invoke()
        self.wait_for(lambda: dialog.status.get() == tr('status.filter.found', n=1))
        row, = dialog.tree.get_children()
        self.assertEqual(dialog.tree.item(row, 'values')[1], str(match))
        dialog.tree.selection_set(row)
        dialog.tree.focus_force()
        dialog.tree.event_generate('<Return>')
        self.wait_for(lambda: self.app.preview is not None and self.app.preview.window.winfo_viewable())
        self.wait_for(lambda: self.app._preview_opened)
        self.assertEqual(self.app.path, match)
        self.app.close_preview()
        self.assertTrue(dialog.winfo_viewable())
        self.assertFalse(self.app.closing)
        self.assertEqual(root.state(), 'withdrawn')
        dialog.close_button.invoke()
        root.after(3000, root.quit)
        self.assertEqual(self.app.run(), 0)
        self.assertTrue(self.app.runner.is_closed)
        self.assertEqual(maps, [])

    def test_filter_shortcut_opens_only_dialog_and_keeps_main_filter_state(self):
        self.start()
        root = self.app.root
        folder = Path(self.directory.name)
        match = folder / 'needle.txt'
        match.write_text('match', encoding='utf-8')
        (folder / 'other.md').write_text('# other', encoding='utf-8')
        self.app.filter_folder.set('unchanged')
        self.app.filter_vars[FileKind.PDF].set(True)
        main_status = self.app.filter_status.get()
        maps = []
        root.bind('<Map>', lambda event: maps.append(event.widget) if event.widget is root else None, add='+')
        listener = self.app.listeners['filter']
        listener.events.append({'type': 'hotkey', 'combo': listener.combo, 'foreground_hwnd': 123})
        with patch('win32gui.GetForegroundWindow', return_value=123), patch.object(self.app.runner, 'submit') as submit:
            self.app._poll_hotkeys()
            request = submit.call_args.args[0]
            self.assertTrue(request.allow_folder)
            self.assertFalse(request.multiple or request.strict_pair)
            result = dict(request_id=request.request_id, code=None, data=SelectionResult(folder, ''))
            with patch.object(self.app.runner, 'poll', side_effect=[[result]] + [[]] * 200):
                self.wait_for(lambda: self.app.filter_dialog is not None and self.app.filter_dialog.winfo_viewable())

        dialog = self.app.filter_dialog
        self.assertEqual(dialog.folder, folder)
        self.assertEqual(dialog.status.get(), tr('status.filter.ready'))
        self.assertEqual([w for w in root.winfo_children() if isinstance(w, tk.Toplevel) and w.winfo_viewable()], [dialog])
        dialog.kind_vars[FileKind.TEXT].set(True)
        dialog.apply_button.invoke()
        self.wait_for(lambda: dialog.status.get() == tr('status.filter.found', n=1))
        self.assertEqual([dialog.tree.item(row, 'values')[1] for row in dialog.tree.get_children()], [str(match)])
        self.assertEqual(self.app.filter_folder.get(), 'unchanged')
        self.assertTrue(self.app.filter_vars[FileKind.PDF].get())
        self.assertFalse(self.app.filter_vars[FileKind.TEXT].get())
        self.assertEqual(self.app.filter_status.get(), main_status)
        self.assertFalse(self.app.filter_tree.get_children())
        dialog.close_button.invoke()

        for foreground, result, expected in (
            (123, dict(code='file_access', message='Select a folder', data=None), 'Select a folder'),
            (456, dict(code=None, data=SelectionResult(folder, '')), tr('status.selection.focus_changed')),
        ):
            self.app.selection_hwnd, self.app.selection_mode = 123, 'filter'
            with patch('win32gui.GetForegroundWindow', return_value=foreground):
                self.app._finish_selection(result)
            self.assertIsNone(self.app.filter_dialog)
            self.assertIn(expected, self.app.filter_shortcut_feedback.get())
        self.assertEqual(root.state(), 'withdrawn')
        self.assertEqual(maps, [])

    def test_filter_shortcut_reopens_busy_dialog_until_scan_finishes(self):
        self.start()
        self.app.open_filter(Path(self.directory.name))
        dialog = self.app.filter_dialog
        self.wait_for(dialog.winfo_viewable)
        entered, release = threading.Event(), threading.Event()

        def scan(*_args, **_kwargs):
            entered.set()
            release.wait(5)
            return ()

        with patch('offlook.core.filter_files', side_effect=scan) as filterer:
            dialog.apply_button.invoke()
            try:
                self.wait_for(entered.is_set)
                dialog.close_button.invoke()
                self.assertEqual(dialog.state(), 'withdrawn')
                listener = self.app.listeners['filter']
                listener.events.append({'type': 'hotkey', 'combo': listener.combo, 'foreground_hwnd': 123})
                with patch.object(self.app.runner, 'submit') as submit:
                    self.app._poll_hotkeys()
                    self.wait_for(dialog.winfo_viewable)
                    submit.assert_not_called()
                self.assertIs(self.app.filter_dialog, dialog)
                filterer.assert_called_once()
                dialog.close_button.invoke()
            finally:
                release.set()
            self.wait_for(lambda: self.app.filter_dialog is None)
        self.assertEqual(self.app.root.state(), 'withdrawn')

    def test_invalid_compare_selection_leaves_preview_usable(self):
        root = Path(self.directory.name)
        paths = tuple(root / f'{index}.txt' for index in range(3))
        suspended = []
        self.app.preview = SimpleNamespace(set_render_suspended=suspended.append)
        try:
            with patch.object(self.app, '_start_comparison') as compare:
                for selected, reason, hwnd in [((), '', 123), (paths[:1], '', 123),
                                                 (paths, '', 123), ((), 'Unsupported view', 123),
                                                 (paths[:2], '', 999)]:
                    with self.subTest(paths=selected, reason=reason, hwnd=hwnd):
                        self.app.selection_hwnd, self.app.selection_mode = 123, 'diff'
                        expected = (tr('status.selection.focus_changed') if hwnd != 123 else
                                    reason or tr('status.selection.two_files'))
                        with patch('win32gui.GetForegroundWindow', return_value=hwnd):
                            self.app._finish_selection(dict(code=None, data=SelectionResult(None, reason, selected)))
                        self.assertIn(expected, self.app.diff_status.get())
                compare.assert_not_called()
            self.assertEqual(suspended, [False] * 5)
        finally:
            self.app.preview = None

    def test_strict_pair_rejects_extra_folder_without_changing_batch_selection(self):
        import pythoncom
        from win32com.client import dynamic

        items = [SimpleNamespace(IsFileSystem=True, IsFolder=folder, Path=name)
                 for name, folder in [('first.txt', False), ('folder', True), ('second.txt', False)]]
        selection = SimpleNamespace(Count=len(items), Item=items.__getitem__)
        folder_view = SimpleNamespace(SelectedItems=lambda: selection)
        view = SimpleNamespace(GetWindow=lambda: 456, GetItemObject=lambda *_: folder_view)
        windows = SimpleNamespace(Count=1, Item=lambda _: SimpleNamespace(HWND=123))
        application = SimpleNamespace(Windows=lambda: windows)
        gui = SimpleNamespace(GetForegroundWindow=lambda: 123, IsWindowVisible=lambda _: True,
                              GetAncestor=lambda *_: 123)
        with patch.object(dynamic, 'Dispatch', side_effect=[application, folder_view] * 2), \
             patch('offlook.platforms.windows_selection._active_view', return_value=view), \
             patch('offlook.platforms.windows_files.validate_local_file', side_effect=Path):
            with self.assertRaisesRegex(FileAccessError, 'exactly two local files'):
                _query_foreground(123, pythoncom, gui, multiple=True, strict_pair=True)
            self.assertEqual(_query_foreground(123, pythoncom, gui, multiple=True),
                             (Path('first.txt'), Path('second.txt')))

    def test_shutdown_retains_tk_until_native_cleanup_finishes(self):
        self.start()
        listener=self.app.listeners['search']
        listener.stop=lambda:None
        self.app.shutdown()
        for _ in range(5):
            self.app.root.update();time.sleep(.02)
        self.assertTrue(self.app.root.winfo_exists())
        listener.is_stopped=True
        self.assertTrue(self.app.closing)



if __name__=='__main__':unittest.main()
