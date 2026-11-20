"""Exercise the installed console command and real spawned preview workers."""
import argparse
import multiprocessing
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import unittest

from offlook.core import FileKind, PreviewConfig
from offlook.preview.models import RasterContent, RenderRequest, TextContent
from offlook.preview.registry import default_renderers
from offlook.preview.worker import WorkerRunner
from qa.smoke_renderer import BlockingTextRenderer

CLI = [sys.executable, '-m', 'offlook']


def wait_for(probe):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if result := probe():
            return result
        time.sleep(0.015)
    raise AssertionError('Timed out waiting for the preview worker')


class WindowsSmoke(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory())).resolve()

    def command(self, *args):
        return subprocess.run([*CLI, *map(str, args)], cwd=self.root, capture_output=True, timeout=10)

    def test_help_and_version(self):
        from importlib.metadata import version

        help_result = self.command('--help')
        self.assertEqual((help_result.returncode, help_result.stderr), (0, b''))
        self.assertIn(b'diagnose-search-shortcut', help_result.stdout)
        result = self.command('--version')
        self.assertEqual((result.returncode, result.stderr), (0, b''))
        self.assertEqual(result.stdout.decode().strip(), version('offlook'))

    def test_combined_filter_and_error(self):
        (self.root / 'nested').mkdir()
        names = ('needle.txt', 'nested/NEEDLE.md', 'needle.csv', '無關.md')
        for name in names:
            (self.root / name).write_text('preview fixture', encoding='utf-8')
        result = self.command('filter', '.', '--name', 'needle', '--kind', 'text', '--kind', 'markdown')
        self.assertEqual((result.returncode, result.stderr), (0, b''))
        self.assertNotIn(b'\r', result.stdout)
        self.assertEqual(set(result.stdout.decode('utf-8').splitlines()), {str(self.root / n) for n in names[:2]})
        result = self.command('filter', '.', '--name', '無關')
        self.assertEqual((result.returncode, result.stdout), (0, f'{self.root / names[-1]}\n'.encode()))
        result = self.command('filter', 'missing')
        self.assertEqual((result.returncode, result.stdout), (2, b''))
        self.assertIn(b'OffLook:', result.stderr)

    def test_compare_exit_contract(self):
        (self.root / 'old.txt').write_text('old\n', encoding='utf-8')
        (self.root / 'new.txt').write_text('new\n', encoding='utf-8')
        self.assertEqual(self.command('compare', 'old.txt', 'old.txt').returncode, 0)
        different = self.command('compare', 'old.txt', 'new.txt')
        self.assertEqual((different.returncode, different.stderr), (1, b''))
        self.assertIn(b'+new\n', different.stdout)
        self.assertEqual(self.command('compare', 'old.txt', 'missing.txt').returncode, 2)

    def runner(self, registry=None):
        previous = {child.pid for child in multiprocessing.active_children()}
        runner = WorkerRunner(registry)

        def close():
            runner.close()
            wait_for(lambda: runner.is_closed)
            self.assertFalse({child.pid for child in multiprocessing.active_children()} - previous)

        self.addCleanup(close)
        return runner

    def test_cancel_started_preview_and_reuse_request_id(self):
        registry = default_renderers()
        registry.register(FileKind.TEXT, BlockingTextRenderer, replace=True)
        runner = self.runner(registry)
        slow, fast = self.root / 'slow.txt', self.root / 'fast.txt'
        slow.write_text('old', encoding='utf-8')
        fast.write_text('new', encoding='utf-8')
        config = PreviewConfig(preview_timeout_seconds=25)
        runner.submit(RenderRequest(9, slow, config))
        wait_for(slow.with_suffix('.started').is_file)
        runner.cancel()
        runner.submit(RenderRequest(9, fast, config))
        result, = wait_for(runner.poll)
        self.assertIsNone(result['code'], result)
        self.assertEqual(result['request_id'], 9)
        self.assertEqual(result['data'].content, TextContent('new'))
        self.assertEqual(runner.poll(), [])

    def test_default_png_and_pdf_loaders(self):
        from PIL import Image

        png, pdf = self.root / 'blue.png', self.root / 'colors.pdf'
        with Image.new('RGB', (60, 60), 'blue') as blue, Image.new('RGB', (60, 60), 'red') as red:
            blue.save(png)
            red.save(pdf, save_all=True, append_images=[blue])
        runner = self.runner()
        config = PreviewConfig(preview_timeout_seconds=10)
        for request_id, (file, page, channel) in enumerate(((png, 0, 2), (pdf, 0, 0), (pdf, 1, 2))):
            runner.submit(RenderRequest(request_id, file, config, page_index=page, max_width=90, max_height=90))
            result, = wait_for(runner.poll)
            self.assertIsNone(result['code'], result)
            data = result['data']
            self.assertEqual(data.page_index, page)
            if file == pdf:
                self.assertEqual(data.page_count, 2)
            image = data.content
            self.assertIsInstance(image, RasterContent)
            center = ((image.height // 2) * image.width + image.width // 2) * 4
            rgb = image.rgba[center:center + 3]
            self.assertGreater(rgb[channel], 220)
            self.assertTrue(all(value < 35 for i, value in enumerate(rgb) if i != channel), rgb)


if __name__ == '__main__':
    multiprocessing.freeze_support()
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--cli', type=Path)
    args, remaining = parser.parse_known_args()
    if args.cli is not None:
        CLI = [str(args.cli.resolve(strict=True))]
    unittest.main(argv=[sys.argv[0], *remaining])
