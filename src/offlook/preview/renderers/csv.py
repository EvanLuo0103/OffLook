"""Bounded CSV/TSV parsing; formulas remain inert strings, never evaluated."""

from __future__ import annotations

import csv
import io

from offlook.core.files import FileInfo
from offlook.preview.models import PreviewData, RenderRequest, TableContent, TextContent
from offlook.preview.renderers.base import Renderer
from offlook.preview.renderers.text import bound_text, read_text


class CsvRenderer(Renderer):
    """Parse at most 200 rows and 50 columns from shared bounded decoded text."""

    def render(self, info: FileInfo, request: RenderRequest) -> PreviewData:
        """Return bounded rows or an explicitly labeled plain-text parse failure."""
        decoded = read_text(info, request, line_limits=False)
        notices = list(decoded.notices)
        truncated = decoded.truncated
        if info.extension == ".tsv":
            dialect = None
            delimiter = "\t"
        else:
            try:
                dialect = csv.Sniffer().sniff(decoded.text[:8192], delimiters=",;\t|")
                delimiter = dialect.delimiter
            except csv.Error:
                dialect = None
                delimiter = ","
                notices.append("Could not automatically determine the delimiter; displaying as comma-separated values")
        csv.field_size_limit(65536)
        stream = io.StringIO(decoded.text, newline="")
        reader = csv.reader(stream, dialect=dialect or "excel", delimiter=delimiter, strict=True)
        rows = []
        total = 0
        try:
            for row in reader:
                # A byte/display cut may leave an apparently valid unquoted tail.
                if decoded.truncated and stream.tell() == len(decoded.text) and not decoded.text.endswith(("\n", "\r")):
                    notices.append("Discarded a potentially incomplete trailing CSV record")
                    truncated = True
                    break
                if len(rows) >= 200:
                    notices.append("Reached the 200-row table display limit")
                    truncated = True
                    break
                if len(row) > 50:
                    notices.append("Content beyond 50 columns was truncated")
                    truncated = True
                cells = []
                exhausted = False
                for cell in row[:50]:
                    if len(cell) > 512:
                        notices.append("Cell exceeded 512 characters and was truncated")
                        truncated = True
                    bounded = cell[:512]
                    remaining = 200000 - total
                    if len(bounded) > remaining:
                        bounded = bounded[:remaining]
                        notices.append("Reached the 200,000-character table display limit")
                        exhausted = truncated = True
                    cells.append(bounded)
                    total += len(bounded)
                    if exhausted:
                        break
                rows.append(tuple(cells))
                if exhausted:
                    break
        except csv.Error as exc:
            if decoded.truncated and "unexpected end of data" in str(exc).lower():
                notices.append("Discarded an incomplete trailing CSV record after truncation")
                truncated = True
            else:
                text, reason = bound_text(decoded.text)
                notices.append("CSV parsing failed; showing the text prefix")
                if reason:
                    notices.append(reason)
                return PreviewData(info, TextContent(text), "; ".join(dict.fromkeys(notices)), truncated or bool(reason))
        return PreviewData(info, TableContent(tuple(rows)), "; ".join(dict.fromkeys(notices)), truncated)
