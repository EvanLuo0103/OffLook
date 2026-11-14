"""Cancellable spawn workers supervised off the UI thread, with bounded pipes.

WorkerRunner methods return without joining processes. Only the supervisor owns
process lifecycle operations; callers poll ordinary result dictionaries. Process
isolation is a cancellation boundary, not a permissions or memory sandbox.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import multiprocessing
import pickle
import queue
import threading
import time
from typing import Any

from offlook.core.errors import FileAccessError, PreviewError
from offlook.core.files import FileKind, FileTypeDetector
from offlook.preview.models import MAX_PREVIEW_PAYLOAD_BYTES, PreviewData, RenderRequest
from offlook.preview.registry import RendererRegistry, default_renderers
from offlook.preview.renderers.base import Renderer
from offlook.preview.renderers.metadata import MetadataRenderer

_CODES = {"file_access", "render_failed", "selection_failed", "timeout", "worker_failed"}


def _validate_data(data: object, request: object) -> None:
    """Recheck unpickled display bounds and result type; raise ValueError if invalid."""
    if isinstance(request, RenderRequest):
        request.__post_init__()
        if not isinstance(data, PreviewData):
            raise ValueError("invalid preview result")
        data.__post_init__()
        data.content.__post_init__()
        from offlook.preview.models import RasterContent
        if isinstance(data.content, RasterContent):
            if data.content.width > request.max_width or data.content.height > request.max_height:
                raise ValueError("result exceeds requested raster bounds")
    else:
        from offlook.platforms.windows_selection import SelectionResult
        from pathlib import Path
        if not isinstance(data, SelectionResult) or (data.path is not None and not isinstance(data.path, Path)):
            raise ValueError("invalid selection result")
        if not isinstance(data.reason, str) or len(data.reason) > 512:
            raise ValueError("invalid selection reason")


def _render_request(request: RenderRequest, renderers: dict[FileKind, type[Renderer]]) -> PreviewData:
    """Detect once and centrally choose content or a safe metadata-only card."""
    info = FileTypeDetector().detect(request.path)
    disabled = info.extension not in request.config.supported_extensions
    oversized_media = info.kind in (FileKind.IMAGE, FileKind.PDF) and info.size_bytes > request.config.max_file_size_bytes
    if disabled or oversized_media or info.kind in (FileKind.BINARY, FileKind.DOCUMENT):
        data = MetadataRenderer().render(info, request)
        if info.kind == FileKind.BINARY:
            notice = "Content preview is not supported for this format"
        elif info.kind == FileKind.DOCUMENT:
            notice = "Document preview is not supported; showing file information only"
        elif oversized_media:
            notice = "Safety preview limit exceeded; showing file information only"
        else:
            notice = "Content preview is not enabled for this extension"
        return replace(data, notice=notice)
    try:
        renderer_type = renderers[info.kind]
    except KeyError as exc:
        raise PreviewError(f"No renderer registered: {info.kind.value}") from exc
    return renderer_type().render(info, request)


def _execute_request(request: object, renderers: dict[FileKind, type[Renderer]]) -> object:
    """Dispatch rendering or lazily imported Shell selection inside the child."""
    if isinstance(request, RenderRequest):
        request.__post_init__()
        return _render_request(request, renderers)
    from offlook.platforms.windows_selection import ExplorerSelectionProvider, SelectionRequest, SelectionResult
    if not isinstance(request, SelectionRequest):
        raise ValueError("unsupported worker request")
    path = ExplorerSelectionProvider().get_selected_file(
        request.foreground_hwnd, for_search=request.for_search
    )
    return SelectionResult(path, "" if path is not None else "The foreground is not a supported Shell view or has changed")


def _worker_target(connection: Any, request: object, renderers: dict[FileKind, type[Renderer]]) -> None:
    """Send exactly one bounded pickle response and always close the child pipe."""
    response = {"request_id": request.request_id, "data": None, "code": None, "message": ""}
    try:
        try:
            data = _execute_request(request, renderers)
            _validate_data(data, request)
            response["data"] = data
        except FileAccessError as exc:
            response.update(code="file_access", message=str(exc)[:512])
        except Exception as exc:
            code = "render_failed" if isinstance(request, RenderRequest) else "selection_failed"
            response.update(code=code, message=f"{type(exc).__name__}：{exc}"[:512])
        payload = pickle.dumps(response, protocol=pickle.HIGHEST_PROTOCOL)
        if len(payload) > MAX_PREVIEW_PAYLOAD_BYTES:
            response.update(data=None, code="worker_failed", message="The preview response exceeds the 36 MiB safety limit")
            payload = pickle.dumps(response, protocol=pickle.HIGHEST_PROTOCOL)
        connection.send_bytes(payload)
    finally:
        connection.close()


def _receive(connection: Any, results: queue.Queue) -> None:
    """Read one bounded complete message off the supervisor/UI threads."""
    try:
        results.put_nowait((True, connection.recv_bytes(maxlength=MAX_PREVIEW_PAYLOAD_BYTES)))
    except Exception as exc:
        results.put_nowait((False, f"Worker process communication failed: {type(exc).__name__}"))


@dataclass
class _Active:
    """Supervisor-owned process, pipe, receiver and request deadline."""

    generation: int
    request: object
    process: Any
    connection: Any
    receiver: threading.Thread
    received: queue.Queue
    deadline: float


class WorkerRunner:
    """One active spawn process; nonblocking submit/cancel/poll/close for Tk.

    Closing is asynchronous: keep polling is_closed before destroying Tk. A new
    submit invalidates every older result even if its request_id was reused.
    """

    def __init__(self, renderers: RendererRegistry | None = None) -> None:
        """Snapshot registrations and start only a supervisor thread, not a process."""
        self._renderers = (renderers if renderers is not None else default_renderers()).snapshot()
        self._context = multiprocessing.get_context("spawn")
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._closed = threading.Event()
        self._generation = 0
        self._pending: tuple[int, object] | None = None
        self._closing = False
        self._results: queue.SimpleQueue = queue.SimpleQueue()
        self._supervisor = threading.Thread(target=self._supervise, name="offlook-supervisor", daemon=True)
        self._supervisor.start()

    @property
    def is_closed(self) -> bool:
        """Return true only after process/pipe/receiver cleanup has completed."""
        return self._closed.is_set()

    def submit(self, request: object) -> None:
        """Queue the latest frozen request; raise PreviewError after close begins."""
        if not isinstance(request, RenderRequest):
            from offlook.platforms.windows_selection import SelectionRequest
            if not isinstance(request, SelectionRequest):
                raise PreviewError("Unsupported worker request")
        else:
            request.__post_init__()
        with self._lock:
            if self._closing:
                raise PreviewError("The preview worker is closed")
            self._generation += 1
            self._pending = (self._generation, request)
        self._wake.set()

    def cancel(self) -> None:
        """Invalidate all earlier work immediately; schedule asynchronous termination."""
        with self._lock:
            self._generation += 1
            self._pending = None
        self._wake.set()

    def poll(self) -> list[dict[str, object]]:
        """Drain current-generation responses without blocking or invoking callbacks."""
        output = []
        with self._lock:
            generation = self._generation
            closing = self._closing
            while True:
                try:
                    result_generation, response = self._results.get_nowait()
                except queue.Empty:
                    break
                if result_generation == generation and not closing:
                    output.append(response)
        return output

    def close(self) -> None:
        """Request cancellation and resource cleanup without joining on the caller."""
        with self._lock:
            if self._closing:
                return
            self._closing = True
            self._generation += 1
            self._pending = None
        self._wake.set()

    def _deliver(self, generation: int, request: object, *, data: object = None, code: str | None = None, message: str = "") -> None:
        """Publish one response only while its generation is still current."""
        with self._lock:
            if generation == self._generation and not self._closing:
                self._results.put((generation, {"request_id": request.request_id, "data": data, "code": code, "message": message[:512]}))

    def _start(self, generation: int, request: object) -> _Active | None:
        """Create one fresh pipe/process; report startup failure with no leaked handles."""
        reader, writer = self._context.Pipe(duplex=False)
        process = self._context.Process(target=_worker_target, args=(writer, request, self._renderers), name="offlook-preview")
        deadline = time.monotonic() + request.config.preview_timeout_seconds
        try:
            process.start()
        except Exception as exc:
            reader.close()
            writer.close()
            if process.pid is not None:
                if process.is_alive():
                    process.terminate()
                process.join()
            process.close()
            self._deliver(generation, request, code="worker_failed", message=f"Cannot start the worker process: {exc}")
            return None
        writer.close()
        received: queue.Queue = queue.Queue(maxsize=1)
        receiver = threading.Thread(target=_receive, args=(reader, received), name="offlook-receiver", daemon=True)
        receiver.start()
        return _Active(generation, request, process, reader, receiver, received, deadline)

    def _dispose(self, active: _Active, *, terminate: bool) -> None:
        """Reap an old process before permitting reuse; only supervisor calls this."""
        process = active.process
        if terminate and process.is_alive():
            process.terminate()
        process.join(0.2)
        if process.is_alive():
            process.kill()
            process.join()
        # The parent write end was closed at start, so reaping the sole writer
        # guarantees that recv_bytes either completes or sees EOF.
        active.receiver.join()
        active.connection.close()
        process.close()

    def _decode(self, payload: bytes, request: object) -> dict[str, object]:
        """Decode a trusted-code response and enforce exact protocol/display bounds."""
        if len(payload) > MAX_PREVIEW_PAYLOAD_BYTES:
            raise ValueError("preview response exceeds 36 MiB safety limit")
        response = pickle.loads(payload)
        if type(response) is not dict or set(response) != {"request_id", "data", "code", "message"}:
            raise ValueError("invalid response keys")
        if type(response["request_id"]) is not int or response["request_id"] != request.request_id:
            raise ValueError("invalid response identifier")
        if not isinstance(response["message"], str) or len(response["message"]) > 512:
            raise ValueError("invalid response message")
        if response["code"] is None:
            if response["message"] != "":
                raise ValueError("invalid success message")
            _validate_data(response["data"], request)
        elif response["code"] not in _CODES or response["data"] is not None:
            raise ValueError("invalid failure response")
        return response

    def _supervise(self) -> None:
        """Own lifecycle operations, enforcing deadlines even during pipe reception."""
        active = None
        try:
            while True:
                self._wake.clear()
                with self._lock:
                    closing = self._closing
                    generation = self._generation
                    pending = self._pending
                    self._pending = None
                if active is not None and (closing or active.generation != generation):
                    self._dispose(active, terminate=True)
                    active = None
                if closing:
                    break
                if pending is not None:
                    active = self._start(*pending)
                if active is not None:
                    if time.monotonic() >= active.deadline:
                        self._dispose(active, terminate=True)
                        self._deliver(active.generation, active.request, code="timeout", message="File rendering timed out" if isinstance(active.request, RenderRequest) else "Shell selection query timed out")
                        active = None
                    else:
                        try:
                            success, payload = active.received.get_nowait()
                        except queue.Empty:
                            # A dead child may still have a complete buffered
                            # message being received. Wait for that or deadline.
                            pass
                        else:
                            self._dispose(active, terminate=not success)
                            if success:
                                try:
                                    response = self._decode(payload, active.request)
                                except Exception as exc:
                                    self._deliver(active.generation, active.request, code="worker_failed", message=f"Invalid worker process response: {type(exc).__name__}")
                                else:
                                    self._deliver(active.generation, active.request, data=response["data"], code=response["code"], message=response["message"])
                            else:
                                self._deliver(active.generation, active.request, code="worker_failed", message=payload)
                            active = None
                self._wake.wait(0.01 if active is not None else 0.1)
        finally:
            if active is not None:
                self._dispose(active, terminate=True)
            self._closed.set()
