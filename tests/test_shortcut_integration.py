"""Deterministic native-boundary regressions using the real withdrawn Tk coordinator."""
from dataclasses import replace
from pathlib import Path
import sys
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import patch

from offlook.core import create_context
from offlook.core.errors import ConfigError
from offlook.gui import PreviewApplication


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
        self.wait_for(lambda:len(self.app.listeners)==3)
    def test_search_failure_does_not_disable_preview_or_diff(self):
        NativeListener.failures={'Ctrl+Q'}
        self.app._reconcile_hotkeys()
        self.wait_for(lambda:set(self.app.listeners)=={'preview','diff'})
        self.assertEqual(self.app.listeners['diff'].combo,'Ctrl+Alt+D')
    def test_preview_failure_does_not_disable_other_actions(self):
        NativeListener.failures={'Ctrl+Space'}
        self.app._reconcile_hotkeys()
        self.wait_for(lambda:set(self.app.listeners)=={'search','diff'})
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
        self.wait_for(lambda:len(self.app.listeners)==3)
    def test_selected_apply_drafts_and_duplicate_rejection(self):
        self.start()
        self.app.action.set('Search files');self.app._select_action()
        self.app.combo.set('Alt+Shift+S')
        self.app.action.set('Git comparison');self.app._select_action()
        self.app.combo.set('Alt+Shift+D')
        self.app.action.set('Search files');self.app._select_action()
        self.assertEqual(self.app.combo.get(),'Alt+Shift+S')
        self.app.apply_button.invoke()
        self.wait_for(lambda:self.app.listeners['search'].combo=='Alt+Shift+S')
        self.app.action.set('Git comparison');self.app._select_action()
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
