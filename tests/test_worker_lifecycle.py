"""Real-spawn lifecycle regressions; no mocked Future, process or decoder."""

import multiprocessing
from pathlib import Path
import sys
import tempfile
import time
import unittest

from offlook.core.errors import PreviewError
from offlook.core.files import FileKind
from offlook.preview.models import RasterContent, RenderRequest
from offlook.preview.registry import default_renderers
from offlook.preview.worker import WorkerRunner
from preview_fixtures import CurrentRenderer, SlowRenderer, close_runner, config, wait_result


@unittest.skipUnless(sys.platform == "win32", "local-file boundary is Windows-only")
class WorkerLifecycleTests(unittest.TestCase):
    """Verify termination, latest-generation delivery and confirmed resource closure."""

    def setUp(self) -> None:
        """Create real fixtures and importable production-registry renderer extensions."""
        self.temp = tempfile.TemporaryDirectory(prefix="offlook-worker-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.slow = self.root / "slow.txt"
        self.slow.write_text("slow real input", encoding="utf-8")
        self.current = self.root / "current.py"
        self.current.write_text("print('inert source')", encoding="utf-8")
        registry = default_renderers()
        registry.register(FileKind.TEXT, SlowRenderer, replace=True)
        registry.register(FileKind.CODE, CurrentRenderer, replace=True)
        self.runner = WorkerRunner(registry)
        self.addCleanup(close_runner, self.runner)
        self.initial_children = {child.pid for child in multiprocessing.active_children()}

    def assert_no_new_children(self) -> None:
        """Assert cleanup left no spawned test process outside the baseline set."""
        remaining = {child.pid for child in multiprocessing.active_children()} - self.initial_children
        self.assertEqual(remaining, set())

    def wait_started(self) -> None:
        """Wait for the slow renderer's real child-side signal, not merely submission."""
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            if self.slow.with_suffix(".started").exists():
                return
            time.sleep(0.01)
        self.fail("spawned SlowRenderer never started")

    def assert_current(self, request_id: int) -> None:
        """Require the new request's own content and identifier, never a stale response."""
        self.runner.submit(RenderRequest(request_id, self.current, config()))
        result = wait_result(self.runner)
        self.assertEqual(result["request_id"], request_id)
        self.assertIsNone(result["code"], result["message"])
        self.assertEqual(result["data"].content.text, "current:current.py")

    def test_hard_timeout_then_normal_request(self) -> None:
        """A 30-second renderer is killed within six seconds and cannot poison reuse."""
        started = time.monotonic()
        self.runner.submit(RenderRequest(1, self.slow, config(preview_timeout_seconds=2.0)))
        result = wait_result(self.runner, timeout=6)
        self.assertEqual(result["request_id"], 1)
        self.assertEqual(result["code"], "timeout")
        self.assertIsNone(result["data"])
        self.assertLess(time.monotonic() - started, 6)
        self.assert_no_new_children()
        self.assert_current(2)
        time.sleep(0.1)
        self.assertEqual(self.runner.poll(), [])
        close_runner(self.runner)
        self.assert_no_new_children()

    def test_replacement_discards_old_generation(self) -> None:
        """Replacing an already-running process yields only the later file's result."""
        self.runner.submit(RenderRequest(10, self.slow, config(preview_timeout_seconds=30.0)))
        self.wait_started()
        self.assert_current(11)
        self.assertEqual(self.runner.poll(), [])
        close_runner(self.runner)
        self.assert_no_new_children()

    def test_cancel_then_reuse_even_with_same_request_id(self) -> None:
        """Cancellation kills active work and generation checks survive ID reuse."""
        self.runner.submit(RenderRequest(20, self.slow, config(preview_timeout_seconds=30.0)))
        self.wait_started()
        started = time.monotonic()
        self.runner.cancel()
        self.assertLess(time.monotonic() - started, 0.2)
        self.assert_current(20)
        close_runner(self.runner)
        self.assert_no_new_children()

    def test_close_is_nonblocking_and_reaps_running_child(self) -> None:
        """Close returns immediately; is_closed waits for actual child/pipe reclamation."""
        self.runner.submit(RenderRequest(30, self.slow, config(preview_timeout_seconds=30.0)))
        self.wait_started()
        started = time.monotonic()
        self.runner.close()
        self.assertLess(time.monotonic() - started, 0.2)
        close_runner(self.runner)
        self.assertTrue(self.runner.is_closed)
        self.assertEqual(self.runner.poll(), [])
        self.assert_no_new_children()
        with self.assertRaises(PreviewError):
            self.runner.submit(RenderRequest(31, self.current, config()))

    def test_real_extension_result_and_repeated_pipe(self) -> None:
        """Importable extension classes execute via spawn and each request owns its pipe."""
        self.assert_current(40)
        self.assert_current(41)
        close_runner(self.runner)
        self.assert_no_new_children()

    def test_large_raster_crosses_former_12_mib_pipe_limit(self) -> None:
        """A 3840x1600 RGBA result traverses spawn IPC under the 36 MiB cap."""
        large = self.root / "large.png"
        # Keep generation in the fixture helper's streaming path; the worker owns decoding.
        from preview_fixtures import png
        png(large, 3840, 1600)
        self.runner.submit(RenderRequest(50, large, config(), max_width=3840, max_height=1600))
        result = wait_result(self.runner, timeout=20)
        self.assertEqual(result["request_id"], 50)
        self.assertIsNone(result["code"], result["message"])
        content = result["data"].content
        self.assertIsInstance(content, RasterContent)
        self.assertEqual((content.width, content.height), (3840, 1600))
        self.assertEqual(len(content.rgba), 3840 * 1600 * 4)
        self.assertEqual(content.rgba[:4], b"\xff\0\0\xff")
        close_runner(self.runner)
        self.assert_no_new_children()
