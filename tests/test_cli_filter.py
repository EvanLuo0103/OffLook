"""User-facing file filter CLI contracts."""
import builtins
from contextlib import redirect_stderr, redirect_stdout
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from offlook.cli import main


@unittest.skipUnless(sys.platform == 'win32', 'OffLook CLI requires Windows')
class FilterCliTests(unittest.TestCase):
    def test_headless_filters_without_loading_desktop_or_config(self):
        original_import = builtins.__import__

        def import_without_gui(name, *args, **kwargs):
            if name.partition('.')[0] == 'tkinter' or name == 'offlook.gui':
                raise AssertionError('Headless filter must not import Tk')
            return original_import(name, *args, **kwargs)

        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            nested = folder / 'nested'
            nested.mkdir()
            hit = nested / 'needle.txt'
            for path in (hit, folder / 'needle.md', folder / 'extra.txt'):
                path.touch()
            stdout, stderr = io.StringIO(), io.StringIO()
            with (
                patch('builtins.__import__', side_effect=import_without_gui),
                patch('offlook.core.context.create_context', side_effect=AssertionError('Unexpected config load')),
                redirect_stdout(stdout),
                redirect_stderr(stderr),
            ):
                result = main(['filter', directory, '--kind', 'text', '--kind', 'markdown',
                               '--ext', 'TXT', '--name', 'NEEDLE'])
            self.assertEqual(result, 0)
            self.assertEqual(stdout.getvalue(), f'{hit}\n')
            self.assertEqual(stderr.getvalue(), '')

    def test_missing_directory_is_error_but_no_matches_is_success(self):
        with tempfile.TemporaryDirectory() as directory:
            for target, expected in ((directory, 0), (str(Path(directory) / 'missing'), 2)):
                with self.subTest(expected=expected):
                    stdout, stderr = io.StringIO(), io.StringIO()
                    with redirect_stdout(stdout), redirect_stderr(stderr):
                        result = main(['filter', target])
                    self.assertEqual(result, expected)
                    self.assertEqual(stdout.getvalue(), '')
                    if expected:
                        self.assertIn('OffLook: Select an existing folder', stderr.getvalue())
                    else:
                        self.assertEqual(stderr.getvalue(), '')

    def test_rejects_incompatible_arguments(self):
        for args, message in (
            (['filter', '.', '--gui', '--name='], '--gui cannot be combined with --name or --ext'),
            (['filter', '.', '--gui', '--ext='], '--gui cannot be combined with --name or --ext'),
            (['--config', 'config.json', 'filter', '.'], '--config is only supported with filter --gui'),
            (['filter', '   '], 'Folder path cannot be empty'),
            (['filter', '.', '--kind', 'unknown'], 'invalid choice'),
        ):
            with self.subTest(args=args), redirect_stderr(io.StringIO()) as stderr:
                with self.assertRaises(SystemExit) as error:
                    main(args)
                self.assertEqual(error.exception.code, 2)
                self.assertIn(message, stderr.getvalue())

    def test_pipe_uses_utf8_paths_even_with_legacy_stdio_encoding(self):
        with tempfile.TemporaryDirectory() as directory:
            match = Path(directory) / '測試.txt'
            match.touch()
            result = subprocess.run(
                [sys.executable, '-m', 'offlook', 'filter', directory, '--kind', 'text'],
                capture_output=True, timeout=15, env={**os.environ, 'PYTHONIOENCODING': 'cp1252'},
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, f'{match}\n'.encode('utf-8'))
        self.assertEqual(result.stderr, b'')
