"""Small real offline fixtures shared by preview-bound and spawn lifecycle tests."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import struct
import time
import zlib

from offlook.core.config import PreviewConfig
from offlook.preview.models import PreviewData, RenderRequest, TextContent
from offlook.preview.renderers.base import Renderer
from offlook.preview.worker import WorkerRunner


def config(**changes: object) -> PreviewConfig:
    """Return a default frozen configuration with only named test overrides."""
    return replace(PreviewConfig(), **changes)


def png(path: Path, width: int = 400, height: int = 200) -> Path:
    """Write valid red RGB PNG incrementally without allocating a full pixel raster."""
    compressor = zlib.compressobj()
    row = b"\0" + b"\xff\0\0" * width
    with path.open("wb") as stream:
        stream.write(b"\x89PNG\r\n\x1a\n")
        _png_chunk(stream, b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        for _ in range(height):
            compressed = compressor.compress(row)
            if compressed:
                _png_chunk(stream, b"IDAT", compressed)
        _png_chunk(stream, b"IDAT", compressor.flush())
        _png_chunk(stream, b"IEND", b"")
    return path


def _png_chunk(stream: object, kind: bytes, data: bytes) -> None:
    """Write one length/type/data/CRC PNG chunk to an already-open binary stream."""
    stream.write(struct.pack(">I", len(data)))
    stream.write(kind)
    stream.write(data)
    stream.write(struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))


def pdf(path: Path) -> Path:
    """Write two valid PDF pages: red portrait then blue landscape, without tools."""
    red = b"1 0 0 rg 0 0 200 400 re f\n"
    blue = b"0 0 1 rg 0 0 400 200 re f\n"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R 5 0 R] /Count 2 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 400] /Resources << >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(red)).encode() + b" >>\nstream\n" + red + b"endstream",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 400 200] /Resources << >> /Contents 6 0 R >>",
        b"<< /Length " + str(len(blue)).encode() + b" >>\nstream\n" + blue + b"endstream",
    ]
    content = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for index, body in enumerate(objects, 1):
        offsets.append(len(content))
        content.extend(f"{index} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = len(content)
    content.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        content.extend(f"{offset:010d} 00000 n \n".encode())
    content.extend(f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    path.write_bytes(content)
    return path


def wait_result(runner: WorkerRunner, timeout: float = 8.0) -> dict[str, object]:
    """Poll a real runner until its first result; raise AssertionError on timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        results = runner.poll()
        if results:
            return results[0]
        time.sleep(0.01)
    raise AssertionError("worker returned no result before test deadline")


def close_runner(runner: WorkerRunner, timeout: float = 4.0) -> None:
    """Request async close and wait outside a UI callback until cleanup is confirmed."""
    runner.close()
    deadline = time.monotonic() + timeout
    while not runner.is_closed and time.monotonic() < deadline:
        time.sleep(0.01)
    if not runner.is_closed:
        raise AssertionError("worker resources did not close")


class SlowRenderer(Renderer):
    """Real importable renderer deliberately exceeding the hard timeout."""

    def render(self, info: object, request: RenderRequest) -> PreviewData:
        """Sleep 30 seconds before returning, proving process termination is required."""
        request.path.with_suffix(".started").write_text("started", encoding="ascii")
        time.sleep(30)
        return PreviewData(info, TextContent("late result must never appear"))


class CurrentRenderer(Renderer):
    """Real importable extension renderer that identifies the current request."""

    def render(self, info: object, request: RenderRequest) -> PreviewData:
        """Return a small deterministic current-file message through the production IPC."""
        return PreviewData(info, TextContent("current:" + request.path.name))
