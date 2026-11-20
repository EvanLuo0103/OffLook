from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

from docx import Document
import pytest

from offlook.core.errors import FileAccessError, PreviewError

from offlook.core import compare_files
from offlook.ui.diff import side_by_side_rows


def test_compare_files_classifies_added_deleted_and_modified_lines(tmp_path: Path):
    old = tmp_path / 'old.md'
    new = tmp_path / 'new.md'
    old.write_bytes(b'same\nmode = old\nqwerty\nanchor\n')
    new.write_bytes(b'same\nmode = new\nanchor\nzxcvbn\n')
    result = compare_files(old, new)
    assert result.changed
    assert {(d.kind, d.old_line, d.new_line, d.emphasis) for d in result.lines} == {
        ('context', 1, 1, ()), ('context', 4, 3, ()),
        ('modified-delete', 2, None, ((7, 10),)), ('modified-add', None, 2, ((7, 10),)),
        ('deleted', 3, None, ()), ('added', None, 4, ()),
    }


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


@pytest.mark.parametrize(('old_data', 'new_data', 'kinds'), [
    (b'x\r\n', b'x\n', {'context'}), (b'qqqq\n', b'zzzz\n', {'deleted', 'added'}),
    (b'', b'one\ntwo\n', {'added'}), (b'', b'', set()),
    (b'\xef\xbb\xbf# x\n', '# x\n'.encode('utf-16'), {'context'}),
    (b'x', b'x\n', {'modified-delete', 'modified-add'}),
    (b'x' * 700 + b'A', b'x' * 700 + b'B', {'deleted', 'added'}),
    (b'a\n' * 65, b'b\n' * 65, {'deleted', 'added'}),
])
def test_line_boundaries_and_unrelated_replacements(tmp_path, old_data, new_data, kinds):
    old, new = tmp_path / 'old', tmp_path / 'new'
    old.write_bytes(old_data)
    new.write_bytes(new_data)
    result = compare_files(old, new)
    assert {line.kind for line in result.lines} == kinds
    assert not any(line.emphasis for line in result.lines)
    if old_data == b'x':
        assert [line.no_newline for line in result.lines] == [True, False]
    if old_data == b'a\n' * 65:
        assert len(result.lines) == 130


def test_word_compares_body_and_tables_not_formatting(tmp_path):
    def word(name, value, bold, header):
        doc = Document()
        doc.add_paragraph().add_run('# 標題').bold = bold
        first, second = doc.add_table(rows=1, cols=2).rows[0].cells
        first.text, second.text = 'Name', value
        doc.sections[0].header.paragraphs[0].text = header
        path = tmp_path / name
        doc.save(path)
        return path

    old = word('old.DOCX', 'Value', False, 'old header')
    formatted = word('formatted.docx', 'Value', True, 'new header')
    new = word('new.docx', 'Value edited', False, '')
    source = tmp_path / 'source.md'
    source.write_bytes('# 標題\nName\tValue\n'.encode('utf-8'))
    assert not compare_files(old, formatted).changed
    assert not compare_files(old, source).changed
    result = compare_files(old, new)
    assert [(d.text, d.old_line, d.new_line) for d in result.lines] == [
        ('# 標題', 1, 1), ('Name\tValue', 2, None), ('Name\tValue edited', None, 2),
    ]


def test_comparison_rejects_unreadable_or_oversized_inputs(tmp_path):
    good = tmp_path / 'good.txt'
    good.write_bytes(b'ok\n')
    bad = tmp_path / 'bad.docx'
    binary = tmp_path / 'binary'
    many = tmp_path / 'many.txt'
    large = tmp_path / 'large.docx'
    bad.write_bytes(b'not a package')
    binary.write_bytes(b'text\0binary')
    many.write_bytes(b'\n' * 20_001)
    with ZipFile(large, 'w', ZIP_DEFLATED) as archive:
        archive.writestr('oversized.xml', b' ' * 16_000_001)
    with pytest.raises(FileAccessError):
        compare_files(tmp_path / 'missing.md', good)
    for path, limit, reason in [(bad, 2_000_000, 'Cannot read Word document'),
                                (binary, 2_000_000, 'supports plain text'),
                                (many, 2_000_000, '20000-line'),
                                (large, 2_000_000, 'unpacking limit')]:
        with pytest.raises(PreviewError, match=reason):
            compare_files(path, good, max_bytes=limit)
    nine = tmp_path / 'nine.txt'
    nine.write_bytes(b'123456789')
    with pytest.raises(PreviewError, match='8-byte'):
        compare_files(nine, good, max_bytes=8)
    assert set(tmp_path.iterdir()) == {good, bad, binary, many, large, nine}
