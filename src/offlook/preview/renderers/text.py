"""Incremental, byte- and display-bounded text decoding shared with CSV."""

from __future__ import annotations

import codecs
from dataclasses import dataclass

from offlook.core.errors import PreviewError
from offlook.core.files import FileInfo
from offlook.preview.models import PreviewData, RenderRequest, TextContent
from offlook.preview.renderers._io import open_checked
from offlook.preview.renderers.base import Renderer


@dataclass(frozen=True)
class DecodedText:
    """Bounded decoded prefix and explicit byte/display/encoding notices."""

    text: str
    notices: tuple[str, ...]
    truncated: bool
    byte_truncated: bool


def bound_text(text: str) -> tuple[str, str]:
    """Return a display-safe prefix and the first exceeded display-limit reason."""
    if len(text) > 200000:
        text = text[:200000]
        reason = "Reached the 200,000-character display limit"
    else:
        reason = ""
    lines = text.splitlines(keepends=True)
    pieces = []
    for index, line in enumerate(lines):
        if index >= 5000:
            return "".join(pieces), "Reached the 5,000-line display limit"
        body = line.rstrip("\r\n\v\f\x1c\x1d\x1e\x85\u2028\u2029")
        if len(body) > 8192:
            pieces.append(body[:8192])
            return "".join(pieces), "Reached the 8,192-character per-line display limit"
        pieces.append(line)
    return "".join(pieces), reason


def read_text(info: FileInfo, request: RenderRequest, *, line_limits: bool = True) -> DecodedText:
    """Decode a bounded prefix incrementally; never finalize a byte-cut character.

    CSV may defer line limits until its text fallback. Invalid decoding and
    uncertain detector confidence are reported; I/O errors remain domain errors.
    """
    encoding = info.encoding or "utf-8"
    try:
        decoder = codecs.getincrementaldecoder(encoding)(errors="replace")
    except LookupError as exc:
        raise PreviewError(f"Unsupported text encoding: {encoding}") from exc
    notices = []
    if info.encoding is None or info.encoding_confidence is None or info.encoding_confidence < 0.70:
        notices.append("Uncertain encoding; decoding using the detected encoding or UTF-8 with replacement")
    byte_truncated = info.size_bytes > request.config.max_file_size_bytes
    if byte_truncated:
        notices.append("Reached the max_file_size_bytes byte limit; showing the text prefix")
    remaining = min(info.size_bytes, request.config.max_file_size_bytes)
    text = ""
    display_reason = ""
    with open_checked(info) as stream:
        while remaining:
            chunk = stream.read(min(8192, remaining))
            if not chunk:
                raise PreviewError("File reading ended early; the file may have changed")
            remaining -= len(chunk)
            text += decoder.decode(chunk, final=False)
            if line_limits:
                text, display_reason = bound_text(text)
            elif len(text) > 200000:
                text = text[:200000]
                display_reason = "Reached the 200,000-character display limit"
            if display_reason:
                break
        if not remaining and not byte_truncated and not display_reason:
            text += decoder.decode(b"", final=True)
            if line_limits:
                text, display_reason = bound_text(text)
            elif len(text) > 200000:
                text = text[:200000]
                display_reason = "Reached the 200,000-character display limit"
    if display_reason:
        notices.append(display_reason)
    if "\ufffd" in text:
        notices.append("Contains undecodable bytes or replacement characters from the original text (shown as �)")
    if info.size_bytes == 0:
        notices.append("Empty file")
    return DecodedText(text, tuple(notices), byte_truncated or bool(display_reason), byte_truncated)


class TextRenderer(Renderer):
    """Render text, code and Markdown as bounded plain text for Tk formatting."""

    def render(self, info: FileInfo, request: RenderRequest) -> PreviewData:
        """Return decoded text and truncation notices; raise on file/codec errors."""
        decoded = read_text(info, request)
        return PreviewData(info, TextContent(decoded.text), "; ".join(decoded.notices), decoded.truncated)
