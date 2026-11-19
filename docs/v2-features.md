# Feature Pack v2 — Conversion, Filtering, and AI Assistant

This document records the second development milestone added on top of the
existing OffLook local previewer. The baseline already contained the core
preview/publish flow (milestone 1) and multi-file search, Git diff, and tests
(milestone 3). This milestone adds the three "group 2" features: local file
conversion, multi-format filtering, and an opt-in AI assistant port.

All new features respect the existing architecture conventions:

- GUI work stays on the Tk main thread; conversion, filtering, and AI run in
  background threads.
- File operations remain offline-first and reject non-local paths.
- Configuration is validated, frozen, and persisted atomically.
- The AI assistant is the only network-capable component, and it is disabled by
  default.

---

## 1. File conversion (default shortcut `Alt+C` → format wheel)

Select one or more files in File Explorer and press `Alt+C` (configurable in
**Shortcut settings**). A radial "wheel" opens next to the pointer and lists
every target format reachable from the current selection; click a target to
convert. The wheel closes with `Esc`, a background click, or focus loss. The
same wheel is available from the **Convert files** card via
**Choose files to convert**.

Output files are written next to the source and never overwrite an existing
file (collisions get a ` (1)` suffix). When the target is PDF and every selected
source is an image, the images are combined into a single PDF.

### Conversion quality modes

The **Convert files** card exposes a **Quality** selector with three modes, so
the user decides whether to keep images/layout:

| Mode | Behavior |
| --- | --- |
| `auto` (default) | Use LibreOffice for high-fidelity document conversion when it is installed; otherwise fall back to text-only (or report a clear error where no text fallback exists). |
| `text` | Text-only conversion: drops images, graphics, and slide layout; produces plain text/PDF/Word from document text. |
| `office` | Require LibreOffice; fail with a clear message if it is not installed. |

Supported conversions (local only; Pillow and pypdfium2 are the hard
dependencies, LibreOffice and `python-docx`/`openpyxl`/`python-pptx` are
optional backends):

| Source | Targets |
| --- | --- |
| Images (PNG/JPEG/BMP/GIF/TIFF/WebP/ICO) | PNG, JPEG, BMP, GIF, TIFF, WebP, ICO, PDF |
| PDF | PNG, JPEG, BMP, TIFF |
| Text / Markdown / Code / CSV | PDF, TXT, Word (.docx) |
| Word (.docx) | PDF (text or LibreOffice), TXT |
| Excel (.xlsx) | CSV, TXT, PDF (LibreOffice) |
| PowerPoint (.pptx) | TXT, Word (.docx, text) · PDF, PNG, JPEG (text or LibreOffice) |

For presentations the `text` mode offers PDF/TXT/Word from slide text; the
`office` mode additionally renders each slide to PNG/JPEG and produces a
layout-preserving PDF through LibreOffice. Word, Excel, and PowerPoint text
extraction uses the optional `python-docx`, `openpyxl`, and `python-pptx`
packages and raises a clear `ConversionError` when they are missing; every other
target keeps working without them.

### Implementation

- `src/offlook/core/conversion.py` — target-format table, per-target converters,
  source classification by extension, output uniquification, and the
  `reachable_targets`/`convert_file`/`convert_files` public API.
- `src/offlook/ui/convert_wheel.py` — borderless radial menu widget.
- `src/offlook/platforms/windows_selection.py` — `get_selected_files` for
  reading a multi-file Explorer selection through the existing COM boundary.
- `src/offlook/preview/worker.py` — multi-selection result validation.

---

## 2. File filtering (multi-format checkbox filter)

The **Filter files** card browses a local folder and lists files matching any
checked combination of formats. Check one or more of Images, PDF, Text,
Markdown, Code, CSV, Documents, or Other, click **Apply filter**, and every
matching file is listed recursively (symlinks and network paths are skipped).
Double-click a result to preview it.

### Implementation

- `src/offlook/core/search.py` — new `filter_files(folder, *, filename, kinds,
  extensions)` function and a shared `_iter_files` walker reused by
  `find_files`.
- `src/offlook/core/file_ops.py` — safe local file-management primitives:
  `list_folder`, `move_files`, `copy_files`, and `organize_by_kind` (which moves
  matching files into per-category subfolders).

---

## 3. AI assistant port (bring your own AI)

The **AI file assistant** card is a provider-neutral port. It is disabled by
default and makes no network request unless the user configures an endpoint and
explicitly runs an instruction.

The user enters an OpenAI-compatible base URL (for example DeepSeek's
`https://api.deepseek.com`), a model (for example `deepseek-chat`), and an API
key, saves the settings, and types a natural-language instruction such as
"move all PDF files in D:\Docs to D:\Archive". The assistant loops through
tool calls locally and shows the final answer together with a transcript of the
tool actions it performed.

### Built-in tools

| Tool | Purpose |
| --- | --- |
| `list_files` | Recursively list local files, optionally by name fragment |
| `filter_files` | List files by extension and/or document kind |
| `move_files` | Move (archive) files into a destination folder |
| `copy_files` | Copy files into a destination folder |
| `organize_by_kind` | Archive files into per-type subfolders |

Each tool validates local drive-letter paths and returns bounded,
JSON-serializable results. Tool arguments are validated and executed locally
before results are returned to the model.

### Implementation

- `src/offlook/core/ai.py` — `AiProvider` interface, the standard-library
  `OpenAiCompatibleProvider`, `AiToolRegistry`, `default_tools`, and the
  `run_instruction` tool-calling loop.

---

## New configuration keys

`PreviewConfig` gained the following fields (defaults shown):

| Field | Default |
| --- | --- |
| `convert_hotkey` | `Alt+C` |
| `convert_mode` | `auto` (also `text` and `office`) |
| `ai_enabled` | `False` |
| `ai_base_url` | `https://api.deepseek.com` |
| `ai_api_key` | `""` |
| `ai_model` | `deepseek-chat` |

The API key is stored in the local configuration file in plain text
(`%LOCALAPPDATA%\OffLook\config.json` by default).

---

## Files added

- `src/offlook/core/conversion.py`
- `src/offlook/core/file_ops.py`
- `src/offlook/core/ai.py`
- `src/offlook/ui/convert_wheel.py`
- `tests/test_conversion.py`
- `tests/test_file_ops.py`
- `tests/test_ai.py`

## Files modified

- `src/offlook/core/__init__.py` — export the new public API
- `src/offlook/core/config.py` — new configuration fields and validation
- `src/offlook/core/errors.py` — `ConversionError` and `AiError`
- `src/offlook/core/search.py` — `filter_files` and shared walker
- `src/offlook/gui.py` — conversion/filter/AI cards, shortcut wiring, workers
- `src/offlook/platforms/windows_selection.py` — multi-file selection
- `src/offlook/preview/worker.py` — multi-selection result validation
- `src/offlook/ui/help.py` — built-in help text
- `README.md`, `docs/api.md`, `docs/getting-started.md` — user documentation

## Testing

`tests/test_conversion.py`, `tests/test_file_ops.py`, and `tests/test_ai.py`
add tests covering conversion output and collision handling, conversion modes
(`auto`/`text`/`office`), presentation text-mode conversion, multi-format
filtering, move/copy/organize, and the AI tool registry and tool-calling loop.

## Known limitations

- The API key is stored in plain text in the local configuration file.
- Word/Excel/PowerPoint text extraction requires optional third-party packages
  that are not part of `requirements.txt`; high-fidelity PDF/image conversion
  requires a LibreOffice installation.
- The AI assistant is the only network feature and only makes requests to the
  endpoint the user configures.
