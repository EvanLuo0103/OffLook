"""Bounded, offline local-file conversion with an explicit target-format table.

Conversions run entirely on the local disk using the already-declared runtime
dependencies (Pillow, pypdfium2). Optional document backends (python-docx,
openpyxl, python-pptx) are imported lazily so their absence only disables the
corresponding document targets; every other target keeps working.

The module never writes over an existing file: output names are uniquified in
the destination directory. Callers own thread selection and must not run this
inside a Tk callback.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from .errors import ConversionError
from .files import _EXTENSION_KINDS, FileKind

# Target formats offered by the conversion wheel. ``extension`` is the canonical
# suffix (lowercased, dot-prefixed) used for outputs; ``label`` is a short
# user-facing name; ``group`` drives how the wheel sections options.
TARGET_FORMATS: tuple[tuple[str, str, str], ...] = (
    (".pdf", "PDF document", "document"),
    (".png", "PNG image", "image"),
    (".jpg", "JPEG image", "image"),
    (".bmp", "BMP image", "image"),
    (".gif", "GIF image", "image"),
    (".tiff", "TIFF image", "image"),
    (".webp", "WebP image", "image"),
    (".ico", "ICO icon", "image"),
    (".txt", "Text file", "text"),
    (".docx", "Word (.docx)", "document"),
    (".xlsx", "Excel (.xlsx)", "document"),
    (".csv", "CSV table", "text"),
    (".extract", "Extract archive", "document"),
)

_LABELS: dict[str, str] = {ext: label for ext, label, _group in TARGET_FORMATS}
_GROUPS: dict[str, str] = {ext: group for ext, _label, group in TARGET_FORMATS}

# Canonical suffix aliases so a caller may pass "pdf", "jpg", or ".jpeg".
_ALIASES: dict[str, str] = {
    "pdf": ".pdf", "png": ".png", "jpg": ".jpg", "jpeg": ".jpg",
    "bmp": ".bmp", "gif": ".gif", "tif": ".tiff", "tiff": ".tiff",
    "webp": ".webp", "ico": ".ico", "txt": ".txt", "text": ".txt",
    "docx": ".docx", "doc": ".docx", "xlsx": ".xlsx", "xls": ".xlsx",
    "csv": ".csv",
    "extract": ".extract",
}

# Source categories that can reach each target. Ordering also drives the wheel's
# availability computation and the automatic multi-image→single-PDF combine.
_TEXT_KINDS = {FileKind.TEXT, FileKind.MARKDOWN, FileKind.CODE, FileKind.CSV}

# Conversion fidelity modes. ``auto`` uses LibreOffice when available and falls
# back to text-only; ``text`` forces text-only (drops images/layout); ``office``
# requires LibreOffice and fails if it is missing.
_CONVERSION_MODES = ("auto", "text", "office")

# Per-target save options for Pillow; JPEG/WebP quality and GIF/ICO handling.
_IMAGE_SAVE_KWARGS: dict[str, dict[str, object]] = {
    ".jpg": {"quality": 92},
    ".webp": {"quality": 92},
}


def normalize_target(target: str) -> str:
    """Return a canonical target suffix or raise ConversionError."""
    if not isinstance(target, str) or not target.strip():
        raise ConversionError("A conversion target format is required")
    key = target.strip().lower().lstrip(".")
    if key == "jpeg":
        key = "jpg"
    if key in _ALIASES:
        return _ALIASES[key]
    if key in _LABELS:
        return key
    raise ConversionError(f"Unsupported conversion target: {target}")


def format_label(target: str) -> str:
    """Return the human-readable label for a canonical target suffix."""
    return _LABELS.get(normalize_target(target), target)


def format_group(target: str) -> str:
    """Return the wheel section name for a canonical target suffix."""
    return _GROUPS.get(normalize_target(target), "document")


def normalize_mode(mode: str = "auto") -> str:
    """Return a canonical conversion mode or raise ConversionError."""
    if mode is None:
        return "auto"
    if not isinstance(mode, str) or mode.strip() not in _CONVERSION_MODES:
        raise ConversionError("The conversion mode must be 'auto', 'text', or 'office'")
    return mode.strip()


def target_formats() -> tuple[str, ...]:
    """Return every canonical target suffix in stable wheel order."""
    return tuple(ext for ext, _label, _group in TARGET_FORMATS)


@dataclass(frozen=True)
class ConversionOutcome:
    """One source file and the output paths produced for it."""

    source: Path
    outputs: tuple[Path, ...]


def _unique_path(directory: Path, stem: str, extension: str) -> Path:
    """Return a non-colliding destination path inside ``directory``."""
    directory.mkdir(parents=True, exist_ok=True)
    counter = 0
    while True:
        suffix = f" ({counter})" if counter else ""
        candidate = directory / f"{stem}{suffix}{extension}"
        try:
            candidate.lstat()
        except FileNotFoundError:
            return candidate
        counter += 1


def _source_kind(path: Path) -> FileKind:
    """Classify a source file for conversion using its extension, not a full read.

    A small content sniff covers suffixless or unknown-extension files. This
    keeps conversion independent of pywin32 so it runs on the plain Python
    runtime used by tests as well as the packaged Windows runtime.
    """
    kind = _EXTENSION_KINDS.get(path.suffix.lower())
    if kind is not None:
        return kind
    try:
        with path.open("rb") as stream:
            sample = stream.read(16)
    except OSError:
        return FileKind.BINARY
    if sample.startswith(b"%PDF-"):
        return FileKind.PDF
    if sample.startswith((b"\x89PNG", b"\xff\xd8\xff", b"GIF87a", b"GIF89a", b"BM", b"RIFF")):
        return FileKind.IMAGE
    return FileKind.BINARY


def _open_image(path: Path):
    """Open a Pillow image and reject unreadable or animated-only sources."""
    try:
        from PIL import Image

        image = Image.open(path)
        image.load()
        return image
    except Exception as exc:
        raise ConversionError(f"Cannot read the image: {exc}") from exc


def _prepared_image(image, extension: str):
    """Return a copy whose mode matches the requested output format."""
    from PIL import Image

    if extension in (".jpg", ".bmp", ".ico"):
        if image.mode in ("RGBA", "LA", "P") or (
            image.mode == "I" or (image.mode == "I;16")
        ):
            if image.mode == "P":
                image = image.convert("RGBA")
            if image.mode in ("RGBA", "LA"):
                background = Image.new("RGB", image.size, (255, 255, 255))
                alpha = image.convert("RGBA").getchannel("A")
                background.paste(image.convert("RGB"), mask=alpha)
                return background
            image = image.convert("RGB")
    if extension == ".gif":
        image = image.convert("P", palette=Image.ADAPTIVE)
    return image


def _save_image(image, destination: Path, extension: str) -> Path:
    """Write one image with format-appropriate parameters."""
    try:
        kwargs = dict(_IMAGE_SAVE_KWARGS.get(extension, {}))
        image.save(destination, **kwargs)
    except Exception as exc:
        raise ConversionError(f"Cannot write {extension.lstrip('.')} output: {exc}") from exc
    return destination


def _convert_image_to_image(source: Path, directory: Path, extension: str) -> tuple[Path, ...]:
    image = _open_image(source)
    try:
        prepared = _prepared_image(image, extension)
        destination = _unique_path(directory, source.stem, extension)
        _save_image(prepared, destination, extension)
        return (destination,)
    finally:
        image.close()


def _convert_image_to_pdf(source: Path, directory: Path) -> tuple[Path, ...]:
    image = _open_image(source)
    try:
        destination = _unique_path(directory, source.stem, ".pdf")
        prepared = image.convert("RGB")
        prepared.save(destination, "PDF", resolution=100.0)
        return (destination,)
    except Exception as exc:
        raise ConversionError(f"Cannot convert the image to PDF: {exc}") from exc
    finally:
        image.close()


def _convert_pdf_to_images(source: Path, directory: Path, extension: str) -> tuple[Path, ...]:
    try:
        import pypdfium2 as pdfium
    except ImportError as exc:
        raise ConversionError("PDF conversion requires the pypdfium2 runtime dependency") from exc
    try:
        document = pdfium.PdfDocument(str(source))
    except Exception as exc:
        raise ConversionError(f"Cannot open the PDF: {exc}") from exc
    outputs: list[Path] = []
    try:
        count = len(document)
        if count == 0:
            raise ConversionError("The PDF has no pages to convert")
        for index in range(count):
            page = document[index]
            bitmap = page.render(scale=2.0)
            pil = bitmap.to_pil()
            destination = _unique_path(directory, f"{source.stem}_page{index + 1}", extension)
            prepared = _prepared_image(pil, extension)
            _save_image(prepared, destination, extension)
            pil.close()
            outputs.append(destination)
    except ConversionError:
        raise
    except Exception as exc:
        raise ConversionError(f"Cannot render the PDF: {exc}") from exc
    finally:
        document.close()
    return tuple(outputs)


def _read_text(source: Path) -> str:
    """Decode a bounded text source without external encoding detectors."""
    if _source_kind(source) not in _TEXT_KINDS:
        raise ConversionError("This file is not a text document")
    try:
        data = source.read_bytes()
    except OSError as exc:
        raise ConversionError(f"Cannot read the file: {exc}") from exc
    for encoding in ("utf-8-sig", "utf-8"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _convert_text_to_txt(source: Path, directory: Path) -> tuple[Path, ...]:
    text = _read_text(source)
    destination = _unique_path(directory, source.stem, ".txt")
    try:
        destination.write_text(text, encoding="utf-8", newline="\n")
    except OSError as exc:
        raise ConversionError(f"Cannot write text output: {exc}") from exc
    return (destination,)


def _load_font(size: int):
    """Return a TrueType font for text rendering, falling back to Pillow's default."""
    from PIL import ImageFont

    for candidate in (
        "C:/Windows/Fonts/consola.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
    ):
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _text_to_pdf(source: Path, directory: Path) -> tuple[Path, ...]:
    text = _read_text(source)
    destination = _unique_path(directory, source.stem, ".pdf")
    _write_raster_pdf(destination, text)
    return (destination,)


def _convert_text_to_docx(source: Path, directory: Path) -> tuple[Path, ...]:
    try:
        import docx
    except ImportError as exc:
        raise ConversionError("Word conversion requires the optional python-docx package") from exc
    text = _read_text(source)
    destination = _unique_path(directory, source.stem, ".docx")
    document = docx.Document()
    for paragraph in text.splitlines() or [""]:
        document.add_paragraph(paragraph)
    try:
        document.save(str(destination))
    except Exception as exc:
        raise ConversionError(f"Cannot write Word output: {exc}") from exc
    return (destination,)


def _docx_paragraphs(source: Path) -> list[str]:
    """Return the paragraph texts of a Word document, requiring python-docx."""
    try:
        import docx
    except ImportError as exc:
        raise ConversionError("Word conversion requires the optional python-docx package") from exc
    try:
        document = docx.Document(str(source))
    except Exception as exc:
        raise ConversionError(f"Cannot open the Word document: {exc}") from exc
    return [paragraph.text for paragraph in document.paragraphs]


def _docx_to_text(source: Path, directory: Path, extension: str) -> tuple[Path, ...]:
    lines = _docx_paragraphs(source)
    destination = _unique_path(directory, source.stem, extension)
    try:
        destination.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    except OSError as exc:
        raise ConversionError(f"Cannot write text output: {exc}") from exc
    return (destination,)


def _xlsx_to_target(source: Path, directory: Path, extension: str) -> tuple[Path, ...]:
    try:
        import openpyxl
    except ImportError as exc:
        raise ConversionError("Excel conversion requires the optional openpyxl package") from exc
    try:
        workbook = openpyxl.load_workbook(str(source), read_only=True, data_only=True)
    except Exception as exc:
        raise ConversionError(f"Cannot open the Excel workbook: {exc}") from exc
    try:
        if extension == ".csv":
            destination = _unique_path(directory, source.stem, ".csv")
            first = workbook.active
            import csv

            try:
                with destination.open("w", encoding="utf-8", newline="") as stream:
                    writer = csv.writer(stream)
                    for row in first.iter_rows(values_only=True):
                        writer.writerow(["" if value is None else str(value) for value in row])
            except OSError as exc:
                raise ConversionError(f"Cannot write CSV output: {exc}") from exc
            return (destination,)
        lines: list[str] = []
        for sheet in workbook.worksheets:
            lines.append(f"[{sheet.title}]")
            for row in sheet.iter_rows(values_only=True):
                lines.append("\t".join("" if value is None else str(value) for value in row))
        destination = _unique_path(directory, source.stem, ".txt")
        destination.write_text("\n".join(lines), encoding="utf-8", newline="\n")
        return (destination,)
    finally:
        workbook.close()


def _pptx_lines(source: Path) -> list[str]:
    """Return slide text lines of a presentation, requiring python-pptx."""
    try:
        import pptx
    except ImportError as exc:
        raise ConversionError("PowerPoint conversion requires the optional python-pptx package") from exc
    try:
        presentation = pptx.Presentation(str(source))
    except Exception as exc:
        raise ConversionError(f"Cannot open the presentation: {exc}") from exc
    lines: list[str] = []
    for index, slide in enumerate(presentation.slides, 1):
        lines.append(f"[Slide {index}]")
        for shape in slide.shapes:
            if getattr(shape, "has_text_frame", False):
                for paragraph in shape.text_frame.paragraphs:
                    text = "".join(run.text for run in paragraph.runs)
                    if text:
                        lines.append(text)
    return lines


def _pptx_to_text(source: Path, directory: Path) -> tuple[Path, ...]:
    lines = _pptx_lines(source)
    destination = _unique_path(directory, source.stem, ".txt")
    destination.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return (destination,)


def _pptx_to_docx(source: Path, directory: Path) -> tuple[Path, ...]:
    """Build a text-only Word document from slide text, requiring python-docx."""
    try:
        import docx
    except ImportError as exc:
        raise ConversionError("Word conversion requires the optional python-docx package") from exc
    lines = _pptx_lines(source)
    destination = _unique_path(directory, source.stem, ".docx")
    document = docx.Document()
    for line in lines or [""]:
        document.add_paragraph(line)
    try:
        document.save(str(destination))
    except Exception as exc:
        raise ConversionError(f"Cannot write Word output: {exc}") from exc
    return (destination,)


def _find_soffice() -> str | None:
    """Locate a LibreOffice ``soffice`` executable, if one is installed."""
    import shutil

    found = shutil.which("soffice")
    if found:
        return found
    for candidate in (
        "C:/Program Files/LibreOffice/program/soffice.exe",
        "C:/Program Files (x86)/LibreOffice/program/soffice.exe",
    ):
        if Path(candidate).is_file():
            return candidate
    return None


def _office_available() -> bool:
    """Return whether LibreOffice is installed and reachable."""
    return _find_soffice() is not None


def _require_soffice() -> str:
    """Return the soffice path or raise a clear, actionable ConversionError."""
    soffice = _find_soffice()
    if soffice is None:
        raise ConversionError(
            "High-fidelity conversion requires LibreOffice; install it or choose Text-only mode"
        )
    return soffice


def _natural_key(path: Path):
    """Sort LibreOffice output naturally so slide/page order survives renaming."""
    import re

    return [int(text) if text.isdigit() else text.casefold() for text in re.split(r"(\d+)", path.name)]


def _office_convert(source: Path, directory: Path, convert_to: str, target_extension: str) -> tuple[Path, ...]:
    """Convert through LibreOffice, moving every result out of a temp directory.

    LibreOffice writes into ``--outdir`` with its own naming (and may emit one
    file per slide for image targets), so results are moved into ``directory``
    with deterministic, collision-free names.
    """
    import shutil
    import subprocess
    import tempfile

    soffice = _require_soffice()
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="offlook-soffice-") as temporary:
        try:
            completed = subprocess.run(
                [
                    soffice, "--headless", "--norestore", "--convert-to", convert_to,
                    "--outdir", temporary, str(source),
                ],
                capture_output=True, timeout=300,
            )
        except subprocess.TimeoutExpired as exc:
            raise ConversionError("LibreOffice conversion timed out") from exc
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or b"").decode("utf-8", "replace").strip()
            raise ConversionError(f"LibreOffice conversion failed{': ' + detail if detail else ''}")
        produced = sorted(Path(temporary).iterdir(), key=_natural_key)
        if not produced:
            raise ConversionError("LibreOffice produced no output")
        outputs: list[Path] = []
        for index, item in enumerate(produced, 1):
            stem = source.stem if len(produced) == 1 else f"{source.stem}_{index}"
            destination = _unique_path(directory, stem, target_extension)
            try:
                shutil.move(str(item), str(destination))
            except OSError as exc:
                raise ConversionError(f"Cannot move LibreOffice output: {exc}") from exc
            outputs.append(destination)
        return tuple(outputs)


def _office_to_pdf(source: Path, directory: Path) -> tuple[Path, ...]:
    """High-fidelity document-to-PDF conversion preserving images and layout."""
    return _office_convert(source, directory, "pdf", ".pdf")


def _word_to_pdf(source: Path, directory: Path) -> tuple[Path, ...]:
    """Convert DOCX to PDF through Microsoft Word using docx2pdf."""
    try:
        from docx2pdf import convert
    except ImportError as exc:
        raise ConversionError(
            "DOCX-to-PDF via Microsoft Word requires the optional docx2pdf package"
        ) from exc

    destination = _unique_path(directory, source.stem, ".pdf")
    try:
        convert(str(source.resolve()), str(destination.resolve()))
    except Exception as exc:
        raise ConversionError(
            "DOCX-to-PDF via Microsoft Word failed. Check that Microsoft Word "
            f"is installed and available: {exc}"
        ) from exc

    if not destination.is_file():
        raise ConversionError("Microsoft Word did not produce a PDF output")

    return (destination,)


def _office_to_images(source: Path, directory: Path, extension: str) -> tuple[Path, ...]:
    """Render each presentation slide to an image via LibreOffice."""
    convert_to = "jpg" if extension == ".jpg" else "png"
    return _office_convert(source, directory, convert_to, extension)


def _html_to_text(source: Path) -> str:
    """Extract readable text from HTML, ignoring script and style contents."""
    from html.parser import HTMLParser

    class TextExtractor(HTMLParser):
        BLOCK_TAGS = {
            "address", "article", "br", "div", "h1", "h2", "h3", "h4",
            "h5", "h6", "li", "p", "section", "tr",
        }

        def __init__(self) -> None:
            super().__init__(convert_charrefs=True)
            self.parts: list[str] = []
            self.hidden_depth = 0

        def handle_starttag(self, tag: str, attrs) -> None:
            if tag in ("script", "style"):
                self.hidden_depth += 1
            elif not self.hidden_depth and tag in self.BLOCK_TAGS:
                self.parts.append("\n")

        def handle_endtag(self, tag: str) -> None:
            if tag in ("script", "style") and self.hidden_depth:
                self.hidden_depth -= 1
            elif not self.hidden_depth and tag in self.BLOCK_TAGS:
                self.parts.append("\n")

        def handle_data(self, data: str) -> None:
            if not self.hidden_depth:
                self.parts.append(data)

    try:
        html = source.read_text(encoding="utf-8", errors="replace")
        parser = TextExtractor()
        parser.feed(html)
        return "\n".join(
            line.strip()
            for line in "".join(parser.parts).splitlines()
            if line.strip()
        )
    except OSError as exc:
        raise ConversionError(f"Cannot read HTML file: {exc}") from exc


# Target converters keyed by canonical suffix. Each converter maps one source
# file to zero-or-more output paths inside ``directory``.
def _convert_single(source: Path, directory: Path, target: str, mode: str = "auto") -> ConversionOutcome:
    """Convert one source file to ``target`` and return its outcome.

    ``mode`` selects fidelity: ``auto`` uses LibreOffice when available and falls
    back to text-only; ``text`` forces text-only output; ``office`` requires
    LibreOffice.
    """
    source = Path(source)
    kind = _source_kind(source)
    extension = normalize_target(target)
    resolved_mode = normalize_mode(mode)
    use_office = resolved_mode == "office" or (resolved_mode == "auto" and _office_available())
    suffix = source.suffix.lower()
    outputs: tuple[Path, ...] = ()
    if extension == ".extract":
        if suffix != ".zip":
            raise ConversionError("Only ZIP archives can be extracted")
        from .archive_extract import extract_archive

        destination = _unique_path(directory, source.stem, "_extracted")
        outputs = extract_archive(source, destination)
    elif extension in (".png", ".jpg", ".bmp", ".gif", ".tiff", ".webp", ".ico"):
        if kind is FileKind.IMAGE:
            outputs = _convert_image_to_image(source, directory, extension)
        elif kind is FileKind.PDF:
            outputs = _convert_pdf_to_images(source, directory, extension)
        elif kind is FileKind.DOCUMENT and suffix in (".pptx", ".pptm"):
            if resolved_mode == "text":
                raise ConversionError("Image output for presentations requires LibreOffice; choose PDF, TXT, or Word")
            outputs = _office_to_images(source, directory, extension)
        else:
            raise ConversionError("Only images, PDFs, and presentations can be converted to image formats")
    elif extension == ".pdf":
        if kind is FileKind.IMAGE:
            outputs = _convert_image_to_pdf(source, directory)
        elif kind in _TEXT_KINDS:
            if suffix in (".html", ".htm"):
                if resolved_mode == "office" or (
                    resolved_mode == "auto" and use_office
                ):
                    outputs = _office_to_pdf(source, directory)
                else:
                    destination = _unique_path(directory, source.stem, ".pdf")
                    _write_raster_pdf(destination, _html_to_text(source))
                    outputs = (destination,)
            else:
                outputs = _text_to_pdf(source, directory)
        elif kind is FileKind.DOCUMENT:
            if suffix == ".docx":
                if resolved_mode == "text":
                    destination = _unique_path(directory, source.stem, ".pdf")
                    _write_raster_pdf(
                        destination,
                        "\n".join(_docx_paragraphs(source)),
                    )
                    outputs = (destination,)
                elif resolved_mode == "office":
                    outputs = _office_to_pdf(source, directory)
                else:  # auto mode: use Microsoft Word
                    outputs = _word_to_pdf(source, directory)
            elif suffix in (".doc", ".xls", ".ppt"):
                outputs = _office_to_pdf(source, directory)
            elif suffix in (".pptx", ".pptm"):
                if use_office:
                    outputs = _office_to_pdf(source, directory)
                else:
                    destination = _unique_path(directory, source.stem, ".pdf")
                    _write_raster_pdf(destination, "\n".join(_pptx_lines(source)))
                    outputs = (destination,)
            elif suffix in (".xlsx", ".xlsm"):
                if not use_office:
                    raise ConversionError("Excel to PDF requires LibreOffice; use CSV or TXT instead")
                outputs = _office_to_pdf(source, directory)
            else:
                raise ConversionError("This document type cannot be converted to PDF")
        else:
            raise ConversionError("This file type cannot be converted to PDF")
    elif extension == ".txt":
        if kind in _TEXT_KINDS:
            if suffix in (".html", ".htm"):
                destination = _unique_path(directory, source.stem, ".txt")
                destination.write_text(
                    _html_to_text(source), encoding="utf-8", newline="\n"
                )
                outputs = (destination,)
            else:
                outputs = _convert_text_to_txt(source, directory)
        elif kind is FileKind.DOCUMENT:
            if suffix == ".docx":
                outputs = _docx_to_text(source, directory, ".txt")
            elif suffix in (".xlsx", ".xlsm"):
                outputs = _xlsx_to_target(source, directory, ".txt")
            elif suffix in (".pptx", ".pptm"):
                outputs = _pptx_to_text(source, directory)
            else:
                raise ConversionError("This document type cannot be converted to text")
        else:
            raise ConversionError("This file type cannot be converted to text")
    elif extension == ".docx":
        if kind in _TEXT_KINDS:
            outputs = _convert_text_to_docx(source, directory)
        elif kind is FileKind.DOCUMENT and suffix in (".pptx", ".pptm"):
            outputs = _pptx_to_docx(source, directory)
        else:
            raise ConversionError("Only text files and presentations can be converted to Word documents")
    elif extension == ".csv":
        if kind is FileKind.CSV:
            text = _read_text(source)
            destination = _unique_path(directory, source.stem, ".csv")
            try:
                destination.write_text(text, encoding="utf-8", newline="\n")
            except OSError as exc:
                raise ConversionError(f"Cannot write CSV output: {exc}") from exc
            outputs = (destination,)
        elif kind is FileKind.DOCUMENT and suffix in (".xlsx", ".xlsm"):
            outputs = _xlsx_to_target(source, directory, ".csv")
        else:
            raise ConversionError("Only spreadsheets can be converted to CSV")
    elif extension == ".xlsx":
        raise ConversionError("Excel output requires a source spreadsheet backend")
    else:
        raise ConversionError(f"Unsupported conversion target: {extension}")
    return ConversionOutcome(source, outputs)


def _write_raster_pdf(destination: Path, text: str) -> None:
    """Render ``text`` onto A4 pages and save a raster PDF (shared helper)."""
    from PIL import Image, ImageDraw

    if not text:
        text = "(empty file)"
    page_width, page_height = 1240, 1754
    margin = 80
    line_height = 44
    font = _load_font(30)
    body_width = page_width - 2 * margin
    pages: list[Image.Image] = []
    current = Image.new("RGB", (page_width, page_height), "white")
    draw = ImageDraw.Draw(current)
    cursor_y = margin

    def new_page() -> tuple[Image.Image, ImageDraw.ImageDraw, int]:
        page = Image.new("RGB", (page_width, page_height), "white")
        return page, ImageDraw.Draw(page), margin

    for paragraph in text.splitlines() or [""]:
        words = paragraph.split(" ")
        line = ""
        for word in words:
            trial = f"{line} {word}".strip()
            box = draw.textbbox((0, 0), trial, font=font)
            if box[2] - box[0] <= body_width:
                line = trial
                continue
            if line:
                draw.text((margin, cursor_y), line, fill="black", font=font)
                cursor_y += line_height
            while word:
                fit = word
                box = draw.textbbox((0, 0), fit, font=font)
                while box[2] - box[0] > body_width and len(fit) > 1:
                    fit = fit[:-1]
                    box = draw.textbbox((0, 0), fit, font=font)
                draw.text((margin, cursor_y), fit, fill="black", font=font)
                cursor_y += line_height
                word = word[len(fit):]
            line = ""
            if cursor_y + line_height > page_height - margin:
                pages.append(current)
                current, draw, cursor_y = new_page()
        if line:
            draw.text((margin, cursor_y), line, fill="black", font=font)
            cursor_y += line_height
        cursor_y += line_height // 2
        if cursor_y + line_height > page_height - margin:
            pages.append(current)
            current, draw, cursor_y = new_page()
    pages.append(current)
    try:
        pages[0].save(destination, "PDF", resolution=150.0, save_all=True, append_images=pages[1:])
    except Exception as exc:
        raise ConversionError(f"Cannot write PDF output: {exc}") from exc
    finally:
        for page in pages:
            page.close()


def _is_image_source(path: Path) -> bool:
    try:
        return _source_kind(path) is FileKind.IMAGE
    except (OSError, ConversionError):
        return False


def convert_file(
    source: str | Path,
    target: str,
    directory: str | Path | None = None,
    mode: str = "auto",
) -> ConversionOutcome:
    """Convert one source file to ``target``, writing outputs next to it by default."""
    source_path = Path(source)
    dest_dir = Path(directory) if directory is not None else source_path.parent
    return _convert_single(source_path, dest_dir, target, mode)


def convert_files(
    sources: Iterable[str | Path],
    target: str,
    directory: str | Path | None = None,
    mode: str = "auto",
) -> tuple[ConversionOutcome, ...]:
    """Convert several sources; images→PDF combine into one document when possible.

    A single target is chosen for all sources. When the target is PDF and every
    source is an image, one combined PDF named after the first source is written;
    otherwise each source is converted independently.
    """
    paths = [Path(source) for source in sources]
    if not paths:
        raise ConversionError("Select at least one file to convert")
    extension = normalize_target(target)
    normalize_mode(mode)
    first_dir = Path(directory) if directory is not None else paths[0].parent
    if extension == ".pdf" and len(paths) > 1 and all(_is_image_source(p) for p in paths):
        from PIL import Image

        images = []
        try:
            for path in paths:
                image = _open_image(path)
                try:
                    images.append(image.convert("RGB"))
                finally:
                    image.close()
            destination = _unique_path(first_dir, paths[0].stem, ".pdf")
            images[0].save(destination, "PDF", resolution=100.0, save_all=True, append_images=images[1:])
        except ConversionError:
            raise
        except Exception as exc:
            raise ConversionError(f"Cannot combine images into PDF: {exc}") from exc
        finally:
            for image in images:
                image.close()
        return (ConversionOutcome(paths[0], (destination,)),)
    return tuple(convert_file(path, extension, directory, mode) for path in paths)


def reachable_targets(sources: Iterable[str | Path], mode: str = "auto") -> tuple[str, ...]:
    """Return targets every selected file can reach, in stable wheel order.

    The wheel hides targets that are impossible for the current selection; this
    function computes the intersection so a mixed selection shows only safe,
    shared targets. ``mode`` follows the same ``auto``/``text``/``office`` rules
    as :func:`convert_file`.
    """
    paths = [Path(source) for source in sources]
    if not paths:
        return ()
    resolved_mode = normalize_mode(mode)
    per_file: list[set[str]] = []
    for path in paths:
        suffix = path.suffix.lower()
        if suffix == ".zip":
            per_file.append({".extract"})
            continue
        if suffix in (".doc", ".xls", ".ppt"):
            per_file.append({".pdf"} if resolved_mode != "text" else set())
            continue
        if suffix in (".html", ".htm"):
            per_file.append({".pdf", ".txt"})
            continue
        try:
            kind = _source_kind(path)
        except (OSError, ConversionError):
            continue
        if kind is FileKind.IMAGE:
            per_file.append({".pdf", ".png", ".jpg", ".bmp", ".gif", ".tiff", ".webp", ".ico"})
        elif kind is FileKind.PDF:
            per_file.append({".png", ".jpg", ".bmp", ".tiff"})
        elif kind in _TEXT_KINDS:
            per_file.append({".pdf", ".txt", ".docx"})
        elif kind is FileKind.DOCUMENT:
            suffix = path.suffix.lower()
            if suffix == ".docx":
                per_file.append({".pdf", ".txt"})
            elif suffix in (".xlsx", ".xlsm"):
                targets = {".csv", ".txt"}
                if resolved_mode in ("auto", "office"):
                    targets.add(".pdf")
                per_file.append(targets)
            elif suffix in (".pptx", ".pptm"):
                if resolved_mode == "text":
                    per_file.append({".pdf", ".txt", ".docx"})
                elif resolved_mode == "office":
                    per_file.append({".pdf", ".png", ".jpg", ".txt"})
                else:
                    per_file.append({".pdf", ".png", ".jpg", ".txt", ".docx"})
            else:
                per_file.append(set())
        else:
            per_file.append(set())
    if not per_file:
        return ()
    common = set(per_file[0])
    for targets in per_file[1:]:
        common &= targets
    return tuple(ext for ext, _label, _group in TARGET_FORMATS if ext in common)


__all__ = [
    "ConversionOutcome",
    "convert_file",
    "convert_files",
    "format_group",
    "format_label",
    "normalize_mode",
    "normalize_target",
    "reachable_targets",
    "target_formats",
]
