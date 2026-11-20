"""Configuration commits reference a credential only after vault verification."""
from contextlib import redirect_stdout
from dataclasses import asdict, replace
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from offlook.cli import main
from offlook.core.config import ConfigManager
from offlook.core.errors import ConfigError
from offlook.core.events import EventBus
from offlook.platforms import windows_credentials as vault


class Credentials(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(TemporaryDirectory()))
        self.path = self.directory / 'profile.json'
        self.path.write_text('{"ai_api_key":"sample-secret"}', encoding='utf-8')
        self.original = self.path.read_bytes()
        self.entries = {}
        self.events = []
        bus = EventBus()
        bus.subscribe('config.changed', self.events.append)
        self.read = self.enterContext(patch.object(vault, 'read_api_key', side_effect=self.entries.get))
        self.write = self.enterContext(patch.object(vault, 'write_api_key', side_effect=self.entries.__setitem__))
        self.delete = self.enterContext(patch.object(vault, 'delete_api_key', side_effect=lambda t: self.entries.pop(t, None)))
        self.manager = ConfigManager(self.path, events=bus)
        self.manager.load()

    def test_migration_keep_replace_and_clear(self):
        m = self.manager
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertTrue(m.has_legacy_ai_key)
        self.read.assert_not_called()
        self.write.assert_not_called()
        m.migrate_legacy_ai_key()
        target = m.ai_credential_target
        self.assertIsNotNone(target)
        self.assertEqual(self.entries[target], 'sample-secret')
        self.assertNotIn('ai_api_key', asdict(m.current))
        self.assertNotIn(b'sample-secret', self.path.read_bytes())
        m.migrate_legacy_ai_key()
        m.update(replace(m.current, always_on_top=True), persist=True)
        self.assertEqual(m.ai_credential_target, target)
        self.write.assert_called_once()
        self.assertNotIn('sample-secret', repr(self.events))
        m.update(m.current, persist=True, ai_key_action='replace', ai_key='next-🔑')
        self.assertNotIn(target, self.entries)
        self.assertEqual(self.entries[m.ai_credential_target], 'next-🔑')
        m.update(m.current, persist=True, ai_key_action='clear')
        self.assertIsNone(m.ai_credential_target)
        self.assertFalse(self.entries)
        self.assertNotIn('ai_credential_id', json.loads(self.path.read_bytes()))

    def test_failed_commit_preserves_original_and_old_key(self):
        self.manager.migrate_legacy_ai_key()
        m = self.manager
        old = m.ai_credential_target
        data = self.path.read_bytes()
        with patch('offlook.core.config.os.replace', side_effect=OSError('fixture failure')):
            with self.assertRaises(ConfigError):
                m.update(replace(m.current, always_on_top=True), persist=True, ai_key_action='replace', ai_key='new-secret')
        self.assertEqual(self.path.read_bytes(), data)
        self.assertEqual(m.ai_credential_target, old)
        self.assertEqual(self.entries, {old: 'sample-secret'})
        self.assertFalse(m.current.always_on_top)
        self.assertFalse(list(self.directory.glob('.offlook-*.tmp')))

    def test_validation_and_stale_guard(self):
        stale = ConfigManager(self.path)
        stale.load()
        m = self.manager
        m.migrate_legacy_ai_key()
        self.write.reset_mock()
        with self.assertRaisesRegex(ConfigError, 'changed on disk'):
            stale.update(stale.current, persist=True)
        self.write.assert_not_called()
        with self.assertRaises(ConfigError):
            m.update(replace(m.current, ai_base_url='https://different.example'), persist=True)
        copied = self.directory / 'copy.json'
        copied.write_bytes(self.path.read_bytes())
        other = ConfigManager(copied)
        other.load()
        self.assertNotEqual(m.ai_credential_target, other.ai_credential_target)
        self.path.write_text('{"ai_api_key":"sample-secret","ai_credential_id":"' + 'a'*32 + '"}')
        with self.assertRaises(ConfigError):
            ConfigManager(self.path).load()

    def test_post_commit_delete_failure_is_not_rollback(self):
        m = self.manager
        m.migrate_legacy_ai_key()
        old = m.ai_credential_target
        self.delete.side_effect = ConfigError('cannot delete')
        m.update(m.current, persist=True, ai_key_action='clear')
        self.assertIn(old, m.credential_warning)
        self.assertIsNone(m.ai_credential_target)
        self.assertNotIn('ai_credential_id', json.loads(self.path.read_bytes()))

    def test_read_only_cli_does_not_migrate(self):
        out = StringIO()
        with redirect_stdout(out):
            self.assertEqual(main(['--config', str(self.path), 'settings', 'show']), 0)
        self.assertNotIn('sample-secret', out.getvalue())
        self.assertEqual(self.path.read_bytes(), self.original)
        self.write.assert_not_called()

    def test_flush_verification_and_partial_vault_write_failures(self):
        m = self.manager
        for failure in ('flush', 'verify', 'write'):
            with self.subTest(failure=failure):
                self.read.side_effect = (lambda target: None) if failure == 'verify' else self.entries.get
                def partial(target, key):
                    self.entries[target] = key
                    if failure == 'write':
                        raise ConfigError('vault unavailable')
                self.write.side_effect = partial
                with patch('offlook.core.config.os.fsync', side_effect=OSError('flush') if failure == 'flush' else None):
                    with self.assertRaises(ConfigError):
                        m.migrate_legacy_ai_key()
                self.assertEqual(self.path.read_bytes(), self.original)
                self.assertTrue(m.has_legacy_ai_key)
                self.assertFalse(self.entries)

    def test_blob_limits_count_utf16_bytes(self):
        self.assertEqual(len(vault._encode_key('🔑'*640)), 2560)
        self.assertEqual(vault._encode_key('é🔑').decode('utf-16-le'), 'é🔑')
        for value in ('🔑'*641, 'bad\x00key'):
            with self.assertRaises(ConfigError):
                vault._encode_key(value)
