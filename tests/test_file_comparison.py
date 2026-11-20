from pathlib import Path

from offlook.core.git_diff import compare_files
from offlook.ui.diff import side_by_side_rows


def test_compare_files_classifies_added_deleted_and_modified_lines(tmp_path: Path):
    old = tmp_path / "old.txt"
    new = tmp_path / "new.txt"
    old.write_text("same\nold value\ndeleted\n", encoding="utf-8")
    new.write_text("same\nnew value\nadded\n", encoding="utf-8")

    result = compare_files(old, new)

    assert result.changed
    kinds = {line.kind for line in result.lines}
    assert "context" in kinds
    assert "modified-delete" in kinds
    assert "modified-add" in kinds


def test_compare_files_reports_identical_files(tmp_path: Path):
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("same\n", encoding="utf-8")
    second.write_text("same\n", encoding="utf-8")

    result = compare_files(first, second)

    assert not result.changed
    assert [line.kind for line in result.lines] == ["context"]


def test_compare_files_distinguishes_pure_insertions_and_deletions(tmp_path: Path):
    old = tmp_path / "old.txt"
    new = tmp_path / "new.txt"
    old.write_text("a\nb\nc\n", encoding="utf-8")
    new.write_text("a\nb\nnew\nc\n", encoding="utf-8")

    result = compare_files(old, new)

    assert "added" in {line.kind for line in result.lines}

    new.write_text("a\nc\n", encoding="utf-8")
    result = compare_files(old, new)

    assert "deleted" in {line.kind for line in result.lines}


def test_compare_files_does_not_mark_every_line_amber(tmp_path: Path):
    old = tmp_path / "old.txt"
    new = tmp_path / "new.txt"
    old.write_text(
        "I like to eat apple.\n"
        "Eating apple is nice since it is delicious and healthy.\n"
        "People Always say eating apple everyday, doctor leave me away.\n",
        encoding="utf-8",
    )
    new.write_text(
        "I hate to eat apple.\n"
        "People Always say eating apple, doctor leave me away.\n"
        "\n"
        "Hello\n",
        encoding="utf-8",
    )

    result = compare_files(old, new)
    kinds = [line.kind for line in result.lines]

    amber_kinds = {"modified-delete", "modified-add"}
    assert "deleted" in kinds
    assert "added" in kinds
    assert sum(kind in amber_kinds for kind in kinds) < len(kinds)


def test_side_by_side_rows_keep_old_on_left_and_new_on_right(tmp_path: Path):
    old = tmp_path / "old.txt"
    new = tmp_path / "new.txt"
    old.write_text("old value\ndeleted\n", encoding="utf-8")
    new.write_text("new value\nadded\n", encoding="utf-8")

    result = compare_files(old, new)
    rows = side_by_side_rows(result)

    assert rows[0].left_text == "old value"
    assert rows[0].right_text == "new value"
    assert rows[0].left_kind == "modified-delete"
    assert rows[0].right_kind == "modified-add"
    assert rows[1].left_text == "deleted"
    assert rows[1].right_text == "added"
