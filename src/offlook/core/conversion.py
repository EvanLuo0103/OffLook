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

    import sys

    soffice = str(Path(_require_soffice()).absolute())
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="offlook-soffice-") as temporary:
        try:
            command = [soffice, '--headless', '--norestore', '--convert-to', convert_to,
                       '--outdir', temporary, str(source)]
            if getattr(sys, 'frozen', False):
                from offlook.platforms.windows_launch import external_process_environment

                process = None
                try:
                    with external_process_environment() as environment:
                        process = subprocess.Popen(command, env=environment, stdout=subprocess.PIPE,
                                                   stderr=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
                    stdout, stderr = process.communicate(timeout=300)
                    completed = subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
                finally:
                    if process is not None:
                        if process.poll() is None:
                            process.kill()
                        process.communicate()
            else:
                completed = subprocess.run(command, capture_output=True, timeout=300)
        except subprocess.TimeoutExpired as exc:
            raise ConversionError("LibreOffice conversion timed out") from exc
        except OSError as exc:
            raise ConversionError('Cannot launch LibreOffice with its own DLL search path') from exc
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
            if resolved_mode == 'text':
                raise ConversionError(f'{source.name}: {conversion_blocker_message("slides_image_mode")}')
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
                    code = 'excel_pdf_mode' if resolved_mode == 'text' else 'libreoffice'
                    raise ConversionError(f'{source.name}: {conversion_blocker_message(code)}')
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


@dataclass(frozen=True)
class ConversionBlocker:
    source: Path
    code: str


class _BackendProbes:
    def __init__(self) -> None:
        self._found: dict[str, bool] = {}

    def has(self, backend: str) -> bool:
        if backend not in self._found:
            self._found[backend] = self._probe(backend)
        return self._found[backend]

    @staticmethod
    def _probe(backend: str) -> bool:
        if backend == 'libreoffice':
            return _find_soffice() is not None
        try:
            if backend == 'word':
                import winreg

                with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r'Word.Application\CLSID',
                                    0, winreg.KEY_READ) as key:
                    value, _ = winreg.QueryValueEx(key, None)
                return isinstance(value, str) and bool(value.strip())
            from importlib.util import find_spec

            return find_spec(backend) is not None
        except (ImportError, ValueError, OSError):
            return False


_SPREADSHEETS = {'.xlsx', '.xlsm'}
_PRESENTATIONS = {'.pptx', '.pptm'}
_LEGACY_OFFICE = {'.doc', '.xls', '.ppt'}
_IMAGE_TARGETS = {'.png', '.jpg', '.bmp', '.gif', '.tiff', '.webp', '.ico'}


def _mode_blocker(source: Path, extension: str, mode: str) -> ConversionBlocker | None:
    suffix = source.suffix.lower()
    if mode == 'text':
        if suffix in _SPREADSHEETS and extension == '.pdf':
            return ConversionBlocker(source, 'excel_pdf_mode')
        if suffix in _PRESENTATIONS and extension in _IMAGE_TARGETS:
            return ConversionBlocker(source, 'slides_image_mode')
    return None


def _conversion_blocker(source: Path, extension: str, mode: str,
                        probes: _BackendProbes) -> ConversionBlocker | None:
    blocked = _mode_blocker(source, extension, mode)
    if blocked:
        return blocked
    suffix = source.suffix.lower()
    required: tuple[str, ...] = ()
    if suffix in _SPREADSHEETS:
        if extension == '.pdf':
            required = ('libreoffice',)
        elif extension in ('.txt', '.csv'):
            required = ('openpyxl',)
    elif suffix in _PRESENTATIONS:
        if extension in _IMAGE_TARGETS:
            required = ('libreoffice',)
        elif extension == '.pdf':
            if mode == 'office':
                required = ('libreoffice',)
            elif mode == 'text' or not probes.has('libreoffice'):
                required = ('pptx',)
        elif extension in ('.txt', '.docx'):
            required = ('pptx',)
    elif extension == '.pdf':
        if suffix == '.docx' and mode == 'auto':
            required = ('docx2pdf', 'word')
        elif suffix in _LEGACY_OFFICE or (mode == 'office' and suffix in ('.docx', '.html', '.htm')):
            required = ('libreoffice',)
    for backend in required:
        if not probes.has(backend):
            return ConversionBlocker(source, backend)
    return None


def conversion_blocker_message(code: str) -> str:
    return {
        'excel_pdf_mode': 'Excel to PDF is unavailable in Text mode; use --mode auto or --mode office (LibreOffice required).',
        'slides_image_mode': 'Presentation images are unavailable in Text mode; use --mode auto or --mode office (LibreOffice required).',
        'libreoffice': 'LibreOffice is required; install it or add soffice to PATH.',
        'openpyxl': 'Install the openpyxl Python package.',
        'pptx': 'Install the python-pptx Python package.',
        'docx2pdf': 'Install the docx2pdf Python package.',
        'word': 'Microsoft Word is not registered; install Word, use Text mode, or use Office mode with LibreOffice.',
    }[code]


def _require_backends(paths: Iterable[Path], extension: str, mode: str) -> None:
    probes = _BackendProbes()
    for source in paths:
        blocker = _conversion_blocker(source, extension, mode, probes)
        if blocker:
            raise ConversionError(f'{source.name}: {conversion_blocker_message(blocker.code)}')


def convert_file(
    source: str | Path,
    target: str,
    directory: str | Path | None = None,
    mode: str = "auto",
) -> ConversionOutcome:
    """Convert one source file to ``target``, writing outputs next to it by default."""
    source_path = Path(source)
    dest_dir = Path(directory) if directory is not None else source_path.parent
    extension, resolved_mode = normalize_target(target), normalize_mode(mode)
    _require_backends((source_path,), extension, resolved_mode)
    return _convert_single(source_path, dest_dir, extension, resolved_mode)


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
    mode = normalize_mode(mode)
    _require_backends(paths, extension, mode)
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
    return tuple(_convert_single(path, Path(directory) if directory is not None else path.parent,
                                 extension, mode) for path in paths)


def _targets_for_source(path: Path, mode: str, *, kind: FileKind | None = None) -> set[str]:
    suffix = path.suffix.lower()
    if suffix == '.zip':
        return {'.extract'}
    if suffix in _LEGACY_OFFICE:
        return {'.pdf'} if mode != 'text' else set()
    if suffix in ('.html', '.htm'):
        return {'.pdf', '.txt'}
    if kind is None:
        kind = _source_kind(path)
    if kind is FileKind.IMAGE:
        return _IMAGE_TARGETS | {'.pdf'}
    if kind is FileKind.PDF:
        return {'.png', '.jpg', '.bmp', '.tiff'}
    if kind in _TEXT_KINDS:
        return {'.pdf', '.txt', '.docx'}
    if kind is FileKind.DOCUMENT:
        if suffix == '.docx':
            return {'.pdf', '.txt'}
        if suffix in _SPREADSHEETS:
            return {'.csv', '.txt'} if mode == 'text' else {'.csv', '.txt', '.pdf'}
        if suffix in _PRESENTATIONS:
            targets = {'.pdf', '.txt'}
            if mode != 'office':
                targets.add('.docx')
            if mode != 'text':
                targets.update(('.png', '.jpg'))
            return targets
    return set()


def reachable_targets(sources: Iterable[str | Path], mode: str = 'auto') -> tuple[str, ...]:
    """List shared format tokens without checking backend availability."""
    paths = [Path(source) for source in sources]
    if not paths:
        return ()
    mode = normalize_mode(mode)
    per_file = []
    for path in paths:
        try:
            per_file.append(_targets_for_source(path, mode))
        except (OSError, ConversionError):
            continue
    common = set.intersection(*per_file) if per_file else set()
    return tuple(target for target, _, _ in TARGET_FORMATS if target in common)


def conversion_options(sources: Iterable[str | Path], mode: str = 'auto'
                       ) -> tuple[tuple[str, ConversionBlocker | None], ...]:
    """List shared targets, with the first mode or dependency blocker for each."""
    paths = tuple(Path(source) for source in sources)
    if not paths:
        return ()
    mode = normalize_mode(mode)
    common = set(target_formats())
    selected: list[tuple[Path, set[str]]] = []
    for path in paths:
        kind = _source_kind(path)
        formats = {choice: _targets_for_source(path, choice, kind=kind) for choice in _CONVERSION_MODES}
        common.intersection_update(set.union(*formats.values()))
        selected.append((path, formats[mode]))
    probes = _BackendProbes()
    options = []
    for target, _, _ in TARGET_FORMATS:
        if target not in common:
            continue
        blocker = None
        for path, allowed in selected:
            if target not in allowed:
                blocker = _mode_blocker(path, target, mode) or ConversionBlocker(
                    path, 'legacy_pdf_mode' if target == '.pdf' else 'slides_docx_mode')
                break
        if blocker is None:
            blocker = next((issue for path in paths if (issue := _conversion_blocker(path, target, mode, probes))), None)
        options.append((target, blocker))
    return tuple(options)


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
