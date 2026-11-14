"""Bounded line-by-line comparison between a working-tree file and Git HEAD."""

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
            for text in old_lines[old_start:old_end]:
                output.append(DiffLine("modified-delete", text, old_number, None))
                old_number += 1
            for text in new_lines[new_start:new_end]:
                output.append(DiffLine("modified-add", text, None, new_number))
                new_number += 1
    return GitComparison(file_path, repository, tuple(output), old_lines != new_lines)
