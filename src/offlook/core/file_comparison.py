"""Bounded, local line comparison for plain text and Word documents."""
from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from difflib import SequenceMatcher
from io import BytesIO
from itertools import groupby
import os
from pathlib import Path
from zipfile import ZipFile

from .errors import FileAccessError, PreviewError
from .files import DOCUMENT_EXTENSIONS, IMAGE_EXTENSIONS, PDF_EXTENSIONS, _bom_encoding, _looks_binary

_MAX_LINES = 20_000
_MAX_WORD_ENTRIES = 1_024
_MAX_WORD_UNPACKED = 16_000_000
_MAX_PAIR_CELLS = 4_096
_MAX_PAIR_WORK = 4_000_000
_MAX_INLINE = 512
_MIN_SIMILARITY = 0.45

_Line = tuple[str, bool]
_Range = tuple[int, int]


@dataclass(frozen=True)
class DiffLine:
    """One source line or shared context; emphasis offsets index Python text."""

    kind: str
    text: str
    old_line: int | None
    new_line: int | None
    emphasis: tuple[_Range, ...] = ()
    no_newline: bool = False


@dataclass(frozen=True)
class FileComparison:
    """An ordered comparison of two existing files' normalized text."""

    old_path: Path
    new_path: Path
    lines: tuple[DiffLine, ...]
    changed: bool


def _unified_rows(lines: tuple[DiffLine, ...]) -> Iterator[DiffLine]:
    for is_context, group in groupby(lines, key=lambda line: line.kind == 'context'):
        if is_context:
            yield from group
        else:
            changed = list(group)
            yield from (line for line in changed if line.old_line is not None)
            yield from (line for line in changed if line.new_line is not None)


@dataclass(frozen=True)
class _Hunk:
    start: int
    stop: int
    header: str


def _hunks(lines: tuple[DiffLine, ...]) -> tuple[_Hunk, ...]:
    ranges: list[tuple[int, int]] = []
    old, new = [0], [0]
    for i, line in enumerate(lines):
        old.append(old[-1] + (line.old_line is not None))
        new.append(new[-1] + (line.new_line is not None))
        if line.kind == 'context':
            continue
        start, stop = max(0, i - 3), min(len(lines), i + 4)
        if ranges and start <= ranges[-1][1]:
            ranges[-1] = ranges[-1][0], stop
        else:
            ranges.append((start, stop))
    hunks = []
    for start, stop in ranges:
        oc, nc = old[stop] - old[start], new[stop] - new[start]
        os, ns = old[start] + bool(oc), new[start] + bool(nc)
        hunks.append(_Hunk(start, stop, f'@@ -{os},{oc} +{ns},{nc} @@'))
    return tuple(hunks)


def _byte_limit(path: Path, max_bytes: int) -> PreviewError:
    return PreviewError(f"File exceeds the {max_bytes}-byte comparison limit: {path}")


def _line_limit(path: Path) -> PreviewError:
    return PreviewError(f"File exceeds the {_MAX_LINES}-line comparison limit: {path}")


def _lf(text: str) -> str:
    return text.replace('\r\n', '\n').replace('\r', '\n')


def _word_text(data: bytes, path: Path, max_bytes: int) -> str:
    try:
        from docx import Document
        from docx.table import Table, _Cell
    except ImportError as exc:
        raise PreviewError(f"Word comparison requires python-docx: {path}") from exc

    contents: list[str] = []
    size = count = 0

    def append(text: str) -> None:
        nonlocal size, count
        text = _lf(text) + '\n'
        size += len(text.encode('utf-8'))
        count += text.count('\n')
        if size > max_bytes:
            raise _byte_limit(path, max_bytes)
        if count > _MAX_LINES:
            raise _line_limit(path)
        contents.append(text)

    try:
        with ZipFile(BytesIO(data)) as archive:
            members = archive.infolist()
            if len(members) > _MAX_WORD_ENTRIES or sum(item.file_size for item in members) > _MAX_WORD_UNPACKED:
                raise PreviewError(f"Word document exceeds the comparison unpacking limit: {path}")
            if len({item.filename for item in members}) != len(members) or any(item.flag_bits & 1 for item in members):
                raise ValueError('Duplicate or encrypted ZIP member')
        document = Document(BytesIO(data))
        for block in document.iter_inner_content():
            if isinstance(block, Table):
                for row in block.rows:
                    # Use the physical cells: row.cells expands merged grid spans.
                    append('\t'.join(_lf(_Cell(cell, block).text).replace('\n', ' ')
                                     for cell in row._tr.tc_lst))
            else:
                append(block.text)
    except PreviewError:
        raise
    except Exception as exc:
        raise PreviewError(f"Cannot read Word document (.docx): {path}") from exc
    return ''.join(contents)


def _read_comparison_lines(path: Path, *, max_bytes: int) -> tuple[_Line, ...]:
    if os.name == 'nt':
        from offlook.platforms.windows_files import validate_local_file

        path = validate_local_file(path)
    try:
        if os.name != 'nt' and not path.is_file():
            raise FileAccessError(f"Select an existing regular file: {path}")
        with path.open('rb') as stream:
            data = stream.read(max_bytes + 1)
    except OSError as exc:
        raise FileAccessError(f"Cannot read comparison file: {path}") from exc
    if len(data) > max_bytes:
        raise _byte_limit(path, max_bytes)

    suffix = path.suffix.lower()
    if suffix == '.docx':
        text = _word_text(data, path, max_bytes)
    else:
        message = f"File comparison supports plain text (UTF-8 or Unicode with BOM) and .docx: {path}"
        if suffix in (*IMAGE_EXTENSIONS, *PDF_EXTENSIONS, *DOCUMENT_EXTENSIONS, '.7z'):
            raise PreviewError(message)
        encoding = _bom_encoding(data)
        if encoding is None and _looks_binary(data):
            raise PreviewError(message)
        try:
            text = data.decode(encoding or 'utf-8')
        except UnicodeDecodeError as exc:
            raise PreviewError(message) from exc
        if '\0' in text:
            raise PreviewError(message)
        text = _lf(text)
    if not text:
        return ()
    terminated = text.endswith('\n')
    if text.count('\n') + (not terminated) > _MAX_LINES:
        raise _line_limit(path)
    parts = text.split('\n')
    last = len(parts) - 1
    return tuple((part, index < last) for index, part in enumerate(parts) if index < last or not terminated)


def _similarity(old: str, new: str) -> float:
    if old == new:
        return 1.0
    if max(len(old), len(new)) > _MAX_INLINE:
        return 0.0
    matcher = SequenceMatcher(None, old, new, autojunk=False)
    return matcher.ratio() if matcher.quick_ratio() >= _MIN_SIMILARITY else 0.0


def _align_replaced_lines(old: tuple[_Line, ...], new: tuple[_Line, ...]) -> list[str]:
    """Pair similar lines in source order, without forcing unrelated replacements."""
    m, n = len(old), len(new)
    old_work = sum(min(len(text), _MAX_INLINE) for text, _ in old)
    new_work = sum(min(len(text), _MAX_INLINE) for text, _ in new)
    if m * n > _MAX_PAIR_CELLS or old_work * new_work > _MAX_PAIR_WORK:
        return ['delete'] * m + ['insert'] * n
    costs = [[0.0] * (n + 1) for _ in range(m + 1)]
    actions = [[''] * (n + 1) for _ in range(m + 1)]
    for i in range(1, m + 1):
        costs[i][0], actions[i][0] = i, 'delete'
    for j in range(1, n + 1):
        costs[0][j], actions[0][j] = j, 'insert'
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            ratio = _similarity(old[i - 1][0], new[j - 1][0])
            options = []
            if ratio >= _MIN_SIMILARITY:
                options.append((costs[i - 1][j - 1] + 1 - ratio, 'modify'))
            options.extend(((costs[i - 1][j] + 1, 'delete'), (costs[i][j - 1] + 1, 'insert')))
            costs[i][j], actions[i][j] = min(options, key=lambda option: option[0])
    result = []
    i, j = m, n
    while i or j:
        action = actions[i][j]
        result.append(action)
        i -= action != 'insert'
        j -= action != 'delete'
    result.reverse()
    return result


def _emphasis(old: str, new: str) -> tuple[tuple[_Range, ...], tuple[_Range, ...]]:
    if old == new or max(len(old), len(new)) > _MAX_INLINE:
        return (), ()
    left, right = [], []
    for tag, i, end_i, j, end_j in SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        if tag in ('replace', 'delete'):
            left.append((i, end_i))
        if tag in ('replace', 'insert'):
            right.append((j, end_j))
    return tuple(left), tuple(right)


def _compare_text(old: tuple[_Line, ...], new: tuple[_Line, ...]) -> tuple[DiffLine, ...]:
    common = min(len(old), len(new))
    prefix = suffix = 0
    while prefix < common and old[prefix] == new[prefix]:
        prefix += 1
    while prefix + suffix < common and old[-suffix - 1] == new[-suffix - 1]:
        suffix += 1
    stop_old, stop_new = len(old) - suffix, len(new) - suffix
    output: list[DiffLine] = []

    def context(i: int, j: int, length: int) -> None:
        for offset in range(length):
            text, ends = old[i + offset]
            output.append(DiffLine('context', text, i + offset + 1, j + offset + 1, no_newline=not ends))

    context(0, 0, prefix)
    middle_old, middle_new = old[prefix:stop_old], new[prefix:stop_new]
    for tag, i, end_i, j, end_j in SequenceMatcher(None, middle_old, middle_new, autojunk=True).get_opcodes():
        if tag == 'equal':
            context(i + prefix, j + prefix, end_i - i)
            continue
        if tag == 'replace':
            actions = _align_replaced_lines(middle_old[i:end_i], middle_new[j:end_j])
        else:
            actions = [tag] * (end_i - i + end_j - j)
        for action in actions:
            if action == 'modify':
                before, old_ends = middle_old[i]
                after, new_ends = middle_new[j]
                left, right = _emphasis(before, after)
                output.append(DiffLine('modified-delete', before, i + prefix + 1, None, left, not old_ends))
                output.append(DiffLine('modified-add', after, None, j + prefix + 1, right, not new_ends))
                i += 1
                j += 1
            elif action == 'delete':
                text, ends = middle_old[i]
                output.append(DiffLine('deleted', text, i + prefix + 1, None, no_newline=not ends))
                i += 1
            else:
                text, ends = middle_new[j]
                output.append(DiffLine('added', text, None, j + prefix + 1, no_newline=not ends))
                j += 1
    context(stop_old, stop_new, suffix)
    return tuple(output)


def compare_files(old_path: str | Path, new_path: str | Path, *, max_bytes: int = 2_000_000) -> FileComparison:
    """Read and compare two local plain-text or DOCX files without writing them."""
    if type(max_bytes) is not int or max_bytes <= 0:
        raise ValueError('max_bytes must be a positive integer')
    old_path, new_path = Path(old_path), Path(new_path)
    old = _read_comparison_lines(old_path, max_bytes=max_bytes)
    new = _read_comparison_lines(new_path, max_bytes=max_bytes)
    return FileComparison(old_path, new_path, _compare_text(old, new), old != new)


def iter_unified_diff(comparison: FileComparison) -> Iterator[str]:
    """Yield unified diff lines without terminators or terminal formatting."""
    if not comparison.changed:
        return
    yield f'--- {comparison.old_path}'
    yield f'+++ {comparison.new_path}'
    for hunk in _hunks(comparison.lines):
        yield hunk.header
        for line in _unified_rows(comparison.lines[hunk.start:hunk.stop]):
            prefix = ' ' if line.kind == 'context' else '-' if line.old_line is not None else '+'
            yield prefix + line.text
            if line.no_newline:
                yield r'\ No newline at end of file'
