"""Behavior tests of the read-only and reviewed built-in AI tool sets."""
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
import unittest
from unittest.mock import patch

from offlook.core.ai import AiError, AiMessageResult, ToolCall, default_tools, run_instruction
from offlook.ui.ai_approval import RunApprovals


class AiSafety(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory()))
        self.source = self.root / 'src' / 'a.txt'
        self.source.parent.mkdir()
        self.source.write_text('original', encoding='utf-8')
        self.dest = self.root / 'dest'
        self.dest.mkdir()
        self.args = {'paths': [str(self.source)], 'destination': str(self.dest)}
        self.enterContext(patch('urllib.request.urlopen', side_effect=AssertionError('unexpected network request')))

    def test_forced_tool_call_with_no_write_tools(self):
        args = self.args
        class Provider:
            calls = 0
            def complete(self, messages, tools):
                if {tool['function']['name'] for tool in tools} != {'list_files', 'filter_files'}:
                    raise AssertionError('mutating tool in read-only definitions')
                self.calls += 1
                if self.calls == 1:
                    return AiMessageResult('', (ToolCall('1', 'move_files', args),), 'tool_calls')
                return AiMessageResult('done', (), 'stop')
        result = run_instruction('archive', provider=Provider())
        self.assertTrue(result.steps[0].error)
        self.assertTrue(self.source.exists())
        self.assertFalse(any(self.dest.iterdir()))

    def test_exact_copy_and_repeated_review(self):
        (self.dest / 'a.txt').write_text('existing', encoding='utf-8')
        approved = []
        def approve(plan):
            approved.append(plan)
            self.assertFalse(plan.items[0].destination.exists())
            return len(approved) == 1
        registry = default_tools(approve_write=approve)
        result = registry.execute('copy_files', self.args)
        renamed = self.dest / 'a (1).txt'
        self.assertEqual(approved[0].items[0].destination, renamed)
        self.assertEqual(result['results'][0]['status'], 'copied')
        self.assertEqual(renamed.read_text(), 'original')
        with self.assertRaisesRegex(AiError, 'not approved'):
            registry.execute('move_files', self.args)
        self.assertEqual(len(approved), 2)
        self.assertTrue(self.source.exists())
        self.assertEqual((self.dest / 'a.txt').read_text(), 'existing')

    def test_changes_during_approval(self):
        def change_target(plan):
            plan.items[0].destination.write_text('other')
            return True
        with self.assertRaises(AiError):
            default_tools(approve_write=change_target).execute('move_files', self.args)
        self.assertTrue(self.source.exists())
        self.assertEqual((self.dest / 'a.txt').read_text(), 'other')
        def change_source(plan):
            self.source.write_text('larger revised source')
            return True
        with self.assertRaises(AiError):
            default_tools(approve_write=change_source).execute('copy_files', self.args)
        self.assertFalse((self.dest / 'a (1).txt').exists())

    def test_no_approval_for_invalid_requests(self):
        registry = default_tools(approve_write=lambda _: self.fail('invalid request reached approval'))
        for args in (dict(self.args, conflict='overwrite'), dict(self.args, paths=['a.txt']),
                     dict(self.args, paths=[r'\\host\share\a']), dict(self.args, paths=self.args['paths'] * 2)):
            with self.subTest(args=args), self.assertRaises(AiError):
                registry.execute('move_files', args)
        src = self.source.parent
        with self.assertRaises(AiError):
            registry.execute('organize_by_kind', {'folder':str(src), 'destination':str(src)})
        for i in range(200): (src / f'file{i}.md').touch()
        with self.assertRaises(AiError):
            registry.execute('organize_by_kind', {'folder':str(src), 'destination':str(self.dest)})
        self.assertFalse(any(self.dest.iterdir()))

    def test_organize_frozen_matches(self):
        other = self.source.with_suffix('.md'); other.touch()
        def approve(plan):
            self.assertEqual(plan.directories, (self.dest / 'text',))
            self.assertEqual(plan.items[0].destination, self.dest/'text'/'a.txt')
            self.assertFalse(any(self.dest.iterdir()))
            self.source.with_name('late.txt').touch()
            return True
        registry = default_tools(approve_write=approve)
        registry.execute('organize_by_kind', {'folder':str(self.source.parent), 'destination':str(self.dest), 'kinds':['text']})
        self.assertTrue(other.exists())
        self.assertTrue(self.source.with_name('late.txt').exists())
        self.assertEqual((self.dest/'text'/'a.txt').read_text(), 'original')

    def test_cancel_and_timeout_do_not_authorize_late_writes(self):
        for timeout in (0.0, 10.0):
            broker = RunApprovals('quick', timeout=timeout)
            decisions = []
            worker = Thread(target=lambda: decisions.append(broker.request(None)))
            worker.start()
            request = broker.requests.get(timeout=1)
            if timeout:
                broker.cancel()
            worker.join(1)
            broker.decide(request, True)
            self.assertEqual(decisions, [False])
            self.assertFalse(broker.request(None))
