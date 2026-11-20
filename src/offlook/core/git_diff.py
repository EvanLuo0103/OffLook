"""Bounded line-by-line comparison for text files and Git working-tree compatibility."""

from __future__ import annotations

from dataclasses import dataclass
import difflib
import os
from pathlib import Path
import subprocess

from .errors import FileAccessError, PreviewError


@dataclass(frozen=True)
class DiffLine:
    """One displayed comparison line and its classification."""

    kind: str
    text: str
    old_line: int | None
    new_line: int | None


@dataclass(frozen=True)
class GitComparison:
    """A bounded comparison result for one tracked working-tree file."""

    path: Path
    repository: Path
    lines: tuple[DiffLine, ...]
    changed: bool


@dataclass(frozen=True)
class FileComparison:
    """A bounded line-by-line comparison of two existing files."""

    old_path: Path
    new_path: Path
    lines: tuple[DiffLine, ...]
    changed: bool


def _align_replaced_lines(
    old_lines: list[str],
    new_lines: list[str],
) -> list[tuple[str, str | None, str | None]]:
    """Pair visibly similar replacement lines and leave unmatched lines as insertions/deletions."""
    old_count = len(old_lines)
    new_count = len(new_lines)
    ratios = [
        [
            difflib.SequenceMatcher(None, old_line, new_line, autojunk=False).ratio()
            for new_line in new_lines
        ]
        for old_line in old_lines
    ]
    costs = [[0.0] * (new_count + 1) for _ in range(old_count + 1)]
    actions = [[""] * (new_count + 1) for _ in range(old_count + 1)]
    for old_index in range(1, old_count + 1):
        costs[old_index][0] = old_index
        actions[old_index][0] = "delete"
    for new_index in range(1, new_count + 1):
        costs[0][new_index] = new_index
        actions[0][new_index] = "insert"

    for old_index in range(1, old_count + 1):
        for new_index in range(1, new_count + 1):
            ratio = ratios[old_index - 1][new_index - 1]
            pair_cost = 1.0 - ratio if ratio >= 0.45 else 1.5
            candidates = (
                (costs[old_index - 1][new_index - 1] + pair_cost, "modify"),
                (costs[old_index - 1][new_index] + 1.0, "delete"),
                (costs[old_index][new_index - 1] + 1.0, "insert"),
            )
            costs[old_index][new_index], actions[old_index][new_index] = min(
                candidates, key=lambda candidate: candidate[0]
            )

    aligned: list[tuple[str, str | None, str | None]] = []
    old_index, new_index = old_count, new_count
    while old_index or new_index:
        action = actions[old_index][new_index]
        if action == "modify":
            old_index -= 1
            new_index -= 1
            aligned.append(("modify", old_lines[old_index], new_lines[new_index]))
        elif action == "delete":
            old_index -= 1
            aligned.append(("delete", old_lines[old_index], None))
        else:
            new_index -= 1
            aligned.append(("insert", None, new_lines[new_index]))
    aligned.reverse()
    return aligned


def _compare_text(old_path: Path, new_path: Path, *, max_bytes: int) -> FileComparison:
    """Read and compare two local UTF-8 text files."""
    for path in (old_path, new_path):
        if not path.is_file():
            raise FileAccessError(f"Select an existing regular file: {path}")
    old_bytes = old_path.read_bytes()
    new_bytes = new_path.read_bytes()
    if len(old_bytes) > max_bytes:
        raise PreviewError(f"The first file exceeds the {max_bytes // 1_000_000} MiB comparison limit")
    if len(new_bytes) > max_bytes:
        raise PreviewError(f"The second file exceeds the {max_bytes // 1_000_000} MiB comparison limit")
    try:
        old_text = old_bytes.decode("utf-8")
        new_text = new_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PreviewError("File comparison supports UTF-8 text files only") from exc
    old_lines = old_text.splitlines()
    new_lines = new_text.splitlines()
    output: list[DiffLine] = []
    old_number = new_number = 1
    for tag, old_start, old_end, new_start, new_end in difflib.SequenceMatcher(
        None, old_lines, new_lines, autojunk=False
    ).get_opcodes():
        if tag == "equal":
            for text in old_lines[old_start:old_end]:
                output.append(DiffLine("context", text, old_number, new_number))
                old_number += 1
                new_number += 1
        elif tag == "delete":
            for text in old_lines[old_start:old_end]:
                output.append(DiffLine("deleted", text, old_number, None))
                old_number += 1
        elif tag == "insert":
            for text in new_lines[new_start:new_end]:
                output.append(DiffLine("added", text, None, new_number))
                new_number += 1
        else:
            replaced_old = old_lines[old_start:old_end]
            replaced_new = new_lines[new_start:new_end]
            for action, old_text, new_text in _align_replaced_lines(replaced_old, replaced_new):
                if action == "modify":
                    assert old_text is not None and new_text is not None
                    output.append(DiffLine("modified-delete", old_text, old_number, None))
                    old_number += 1
                    output.append(DiffLine("modified-add", new_text, None, new_number))
                    new_number += 1
                elif action == "delete":
                    assert old_text is not None
                    output.append(DiffLine("deleted", old_text, old_number, None))
                    old_number += 1
                else:
                    assert new_text is not None
                    output.append(DiffLine("added", new_text, None, new_number))
                    new_number += 1
    return FileComparison(old_path, new_path, tuple(output), old_lines != new_lines)


def compare_files(
    old_path: str | Path,
    new_path: str | Path,
    *,
    max_bytes: int = 2_000_000,
) -> FileComparison:
    """Compare two local UTF-8 text files line by line."""
    return _compare_text(Path(old_path), Path(new_path), max_bytes=max_bytes)


def compare_with_head(path: str | Path, *, max_bytes: int = 2_000_000) -> GitComparison:
    """Compare a tracked UTF-8-compatible file with its latest committed version."""
    file_path = Path(path)
    if not file_path.is_file():
        raise FileAccessError("Select an existing regular file to compare")
    try:
        root_result = subprocess.run(
            ["git", "-C", str(file_path.parent), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise PreviewError("Git is unavailable; install Git for Windows to compare files") from exc
    if root_result.returncode != 0:
        detail = root_result.stderr.strip()
        raise PreviewError(
            f"The selected file is not inside a Git repository{': ' + detail if detail else ''}"
        )
    repository = Path(root_result.stdout.strip())
    try:
        relative = file_path.resolve().relative_to(repository.resolve())
    except ValueError as exc:
        raise FileAccessError("The selected file is outside the Git repository") from exc
    try:
        current = file_path.read_bytes()
        if len(current) > max_bytes:
            raise PreviewError("The working-tree file exceeds the 2 MiB comparison limit")
        committed_result = subprocess.run(
            ["git", "-C", str(repository), "show", f"HEAD:{relative.as_posix()}"],
            capture_output=True, timeout=5, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise PreviewError("Git could not read the committed file version") from exc
    if committed_result.returncode != 0:
        detail = committed_result.stderr.decode("utf-8", errors="replace").strip()
        raise PreviewError(
            f"The selected file is not tracked in the latest Git commit{': ' + detail if detail else ''}"
        )
    committed = committed_result.stdout
    if len(committed) > max_bytes:
        raise PreviewError("The committed file exceeds the 2 MiB comparison limit")
    try:
        old_text = committed.decode("utf-8")
        new_text = current.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PreviewError("Git comparison currently supports UTF-8 text files only") from exc
    old_lines = old_text.splitlines()
    new_lines = new_text.splitlines()
    output: list[DiffLine] = []
    old_number = new_number = 1
    for tag, old_start, old_end, new_start, new_end in difflib.SequenceMatcher(
        None, old_lines, new_lines, autojunk=False
    ).get_opcodes():
        if tag == "equal":
            for text in old_lines[old_start:old_end]:
                output.append(DiffLine("context", text, old_number, new_number))
                old_number += 1
                new_number += 1
        elif tag == "delete":
            for text in old_lines[old_start:old_end]:
                output.append(DiffLine("deleted", text, old_number, None))
                old_number += 1
        elif tag == "insert":
            for text in new_lines[new_start:new_end]:
                output.append(DiffLine("added", text, None, new_number))
                new_number += 1
        else:
            replaced_old = old_lines[old_start:old_end]
            replaced_new = new_lines[new_start:new_end]
            for action, old_text, new_text in _align_replaced_lines(replaced_old, replaced_new):
                if action == "modify":
                    assert old_text is not None and new_text is not None
                    output.append(DiffLine("modified-delete", old_text, old_number, None))
                    old_number += 1
                    output.append(DiffLine("modified-add", new_text, None, new_number))
                    new_number += 1
                elif action == "delete":
                    assert old_text is not None
                    output.append(DiffLine("deleted", old_text, old_number, None))
                    old_number += 1
                else:
                    assert new_text is not None
                    output.append(DiffLine("added", new_text, None, new_number))
                    new_number += 1
    return GitComparison(file_path, repository, tuple(output), old_lines != new_lines)
