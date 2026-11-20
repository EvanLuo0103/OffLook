# OffLook API quick start

Minimal interfaces for contributors. Keep previews, comparisons, and local extension callbacks offline; only an explicitly run AI assistant contacts its configured service. Do not read files or run time-consuming work in Tk callbacks. External plugins are not automatically discovered or executed.

## Create a context and identify files

```python
from offlook.core import create_context, FileTypeDetector
context = create_context()
info = FileTypeDetector().detect("README.md")
print(info.kind.value, info.path, info.size_bytes)
```

To search a local folder recursively without reading file contents:

```python
from offlook.core import FileKind, find_files
results = find_files("C:/Documents", filename="report", kind=FileKind.PDF)
```

`filter_files` is the multi-select companion. A file must match the optional case-insensitive `filename` substring **and** each nonempty filter group: any kind in `kinds` **and** any suffix in `extensions`. Within a group, values are alternatives. An empty group imposes no restriction. Both functions classify by extension without reading contents, skip symbolic links, and skip inaccessible subfolders.

```python
from offlook.core import FileKind, filter_files
results = filter_files("C:/Documents", kinds=[FileKind.PDF, FileKind.IMAGE])
```

FileInfo contains path, kind, size_bytes, modified_time_ns, extension, encoding, and encoding_confidence. Detection synchronously reads up to 64 KiB and accepts only local regular files. Kinds are image/text/markdown/pdf/code/csv/document/binary; document and binary classifications display metadata rather than parsed contents.

## Compare two local files

```python
from offlook.core import compare_files

comparison = compare_files('before.md', 'after.docx')
print(comparison.changed)
for line in comparison.lines:
    print(line.kind, line.old_line, line.new_line, line.text)
```

`compare_files(old_path, new_path, *, max_bytes=2_000_000)` reads and parses both local files synchronously without rewriting them or creating intermediate files. Run it off the Tk thread. It compares only the two supplied paths, not Git HEAD, and has no CLI subcommand.

- Plain text is decoded strictly as UTF-8 unless a UTF-8, UTF-16, or UTF-32 byte-order mark specifies the encoding. This includes TXT, Markdown, RST, CSV/TSV, code, and extensionless text. Markdown and HTML are compared as source, not rendered output. Binary data and unsupported formats such as PDF, legacy `.doc`, and spreadsheets are rejected.
- Word `.docx` comparison uses the installed `python-docx` dependency, not Word or LibreOffice, and can be mixed with plain text. It extracts top-level body paragraphs and table rows in document order; physical cells are separated by tabs and cell line breaks become spaces. Nested tables and content outside the main body, such as headers, footers, and comments, are not extracted. Layout and images are not compared. DOCX line numbers refer to extracted text rather than Word pages.
- CRLF and lone CR are normalized to LF. Blank lines, surrounding whitespace, and the presence or absence of a final newline still matter. Empty text has zero lines. No Unicode normalization is applied.
- The byte limit applies per input and also to each DOCX's extracted text encoded as UTF-8. `max_bytes` must be a positive integer (not `bool`), or `ValueError` is raised. Each input is limited to 20,000 lines; DOCX containers are limited to 1,024 members and 16,000,000 bytes of declared uncompressed data. Over-limit inputs are rejected, not truncated.
- `FileAccessError` reports invalid paths or failures to open or read the source. `PreviewError` reports unsupported input, decoding failures, DOCX parsing failures (including an unavailable dependency, invalid archives, duplicate ZIP members, or encrypted members), and limit violations.

`FileComparison` exposes `old_path` and `new_path` as `Path` objects, `lines` as a tuple of `DiffLine` records, and `changed` as a boolean indicating whether the normalized line sequences differ. Each `DiffLine` has:

| Field | Meaning |
| --- | --- |
| `kind` | `context`, `deleted`, `added`, `modified-delete`, or `modified-add`. The last two are the old and new sides of a paired edit and count as a deletion and an addition, respectively. |
| `text` | Line text without its trailing LF. |
| `old_line`, `new_line` | One-based source line numbers; `None` on the side where the line is absent. |
| `emphasis` | A tuple of half-open `(start, end)` ranges into the Python string `text`; empty if no inline emphasis is available. |
| `no_newline` | True when this is an unterminated final line. |

## Open a preview

```python
from offlook.preview import launch_preview
if __name__ == "__main__":
    raise SystemExit(launch_preview("README.md", always_on_top=True))
```

Call from the main thread; an exit code is returned when the window closes. Do not launch this application inside a host with an existing Tk instance. The GUI renders in a terminable spawn process and ignores stale requests.

## Register contributor callbacks

```python
from pathlib import Path
from offlook.core import create_context, ActionRequest
context = create_context()
def describe(request, context):
    """Return request paths without implementing file-processing business."""
    return tuple(str(path) for path in request.paths)
context.actions.register("describe", describe)
print(context.actions.invoke("describe", ActionRequest((Path("README.md"),), {}), context))
context.actions.unregister("describe")
```

Callbacks run synchronously. Duplicate names, unregistered actions, and callback exceptions raise ExtensionError. Callbacks are trusted code, not a sandbox; they must follow the offline and threading rules themselves.

## Configuration and events

`context.config.current` is a frozen PreviewConfig. `update(config, persist=True)` saves atomically and leaves in-memory state unchanged on failure. Use dataclasses.replace to create an updated instance. Fields:

| Field | Meaning / default |
| --- | --- |
| max_file_size_bytes | 10,485,760 bytes |
| preview_timeout_seconds | 5 seconds |
| hotkey_enabled | True; shared enable gate for Preview, Search files, File comparison, and Convert files |
| hotkey | Ctrl+Space; Preview shortcut |
| search_hotkey | Ctrl+Q; prepares a local folder for Search files without starting a search |
| diff_hotkey | Ctrl+Alt+D; Compare files shortcut |
| convert_hotkey | Alt+C; opens the **Convert to** dropdown dialog |
| convert_mode | `auto`; also `text` and `office`. Backend choice depends on the source and target. |
| always_on_top | False |
| supported_extensions | Tuple of supported extensions; an empty collection shows metadata only |
| ai_enabled / ai_base_url / ai_api_key / ai_model | `False` / `https://api.deepseek.com` / `""` / `deepseek-chat`. `ai_enabled` is a saved preference, not a runtime gate. The key is saved in plaintext in JSON. |
| language | en; also zh. Selects the interface language; `offlook.ui.i18n.tr` reads it. |

The four combinations are canonicalized with `parse_hotkey` and must be pairwise distinct even when `hotkey_enabled` is false. Invalid syntax raises `ConfigError` with its `HotkeyError` cause; duplicate errors name both conflicting fields. Missing shortcut fields in old JSON use defaults without rewriting the file; existing collisions are configuration errors, not silently reset. These combinations are defaults, not permanently reserved keys.

The resident GUI's **Enable global shortcuts** switch immediately persists the shared gate. Its Preview / Search files / Compare files / Convert files selector maintains separate drafts; **Apply** saves only the selected key. While enabled, a replacement is registered before saving, and the old active key remains on registration or persistence failure. While disabled, Apply only saves. External updates reconcile only shortcut fields and the shared gate; other settings do not rebind keys. Each action registers independently, and statuses distinguish configured keys from active registrations. An external cross-action swap requires an intermediate unused combination rather than an unregister-first swap. `launch_preview` and the single-file CLI command register no global shortcuts.

`offlook.ui.help.show_help(parent, *, shortcuts)` creates the offline Help window; `update_help_shortcuts(window, *, shortcuts)` refreshes its text in place without focusing it and preserves its scroll position. Both accept a mapping with `preview`, `search`, `diff`, and `convert` keys containing the rendered registration statuses.

`py -m offlook --config '<path>' diagnose-search-shortcut` loads the specified config before creating only the configured search listener and Explorer selection provider; it creates no GUI. It tests `search_hotkey` even with the shared gate disabled, without saving settings. Release that key in the main app and other instances first. Ctrl+C exits the diagnostic with code 0; invalid or missing explicit config exits with code 2.

`events.subscribe(topic, callback)` returns an unsubscribe function. The callback receives Event(topic, payload) synchronously on the publishing thread.

| topic | payload |
| --- | --- |
| config.changed | config |
| preview.requested / preview.closed | path |
| preview.opened | file_info, once for the first frame |
| preview.failed | path, code, message |

## Convert, filter, and manage files

Conversion runs locally using Pillow and pypdfium2, with document backends where needed. `convert_file(source, target, directory=None, mode="auto")` returns one `ConversionOutcome` with `source` and `outputs` (a tuple of output paths). `convert_files(sources, target, directory=None, mode="auto")` returns a tuple of outcomes. Multiple images targeting PDF produce one combined document named after the first source and one outcome. Other batches convert files individually.

By default, each output goes next to its source (the first source for a combined PDF); pass `directory` to choose a different location. Existing names get numbered alternatives. This naming is not a guarantee against collisions between concurrent writers.

```python
from offlook.core import convert_file, reachable_targets, target_formats

print(target_formats())                      # recognized target tokens, in dialog order
print(reachable_targets(["a.png", "b.jpg"]))  # targets shared by the selection
outcome = convert_file("a.png", "pdf")
print(outcome.outputs)
```

`target_formats()` lists recognized tokens, not implemented conversions for every source: `.xlsx` does not promise Excel output, and `.extract` is the ZIP extraction operation, not an output suffix. `reachable_targets(sources, mode="auto")` intersects the targets for all sources, but does not check that the required backends are installed. The GUI uses it for the **Convert to** dropdown. With the shortcut, the dialog opens without restoring the main window and keeps progress, output paths, or errors in the same window.

`convert_file`, `convert_files`, and `reachable_targets` accept `mode="auto"`, `"text"`, or `"office"`. The backend depends on the source and target:

| Source | Outputs and backend behavior |
| --- | --- |
| Images, PDFs, text | Images convert to other image formats or PDF; PDFs convert to images; text, Markdown, code, and CSV convert to PDF, TXT, or DOCX. These operations do not require Office. |
| DOCX | TXT and `text`-mode PDF use paragraphs via `python-docx`, an installed runtime dependency. `auto`-mode PDF uses Microsoft Word with optional `docx2pdf` and does not fall back automatically; `office`-mode PDF uses LibreOffice. |
| XLSX / XLSM | CSV and TXT require optional `openpyxl`; PDF requires LibreOffice in `auto` or `office` mode. |
| PPTX / PPTM | `text`-mode PDF, TXT, and DOCX use slide text via optional `python-pptx`. PNG/JPEG and layout-preserving PDF require LibreOffice. For PDF, `auto` uses LibreOffice when available and slide text otherwise. |
| Legacy `.doc`, `.xls`, `.ppt` | PDF requires LibreOffice. The dialog offers it in `auto` or `office` mode. |
| HTML | TXT uses extracted text. PDF uses LibreOffice in `office` mode or when available in `auto`; otherwise it uses extracted text. |
| ZIP | `.extract` unpacks the archive into a new folder. |

```python
outcome = convert_file("deck.pptx", "pdf", mode="office")  # requires LibreOffice
```

Unsupported conversions and missing required backends raise `ConversionError`. Local file management is in `offlook.core.file_ops`:

```python
from offlook.core import move_files, organize_by_kind, FileKind
results = move_files(["a.pdf"], "C:/Archive")            # archive files
results = organize_by_kind("C:/Docs", "C:/Archive", kinds=[FileKind.PDF])
```

## AI assistant port

The provider-neutral assistant is opt-in: creating a provider or saving AI settings does not contact the service. The built-in `OpenAiCompatibleProvider` uses the standard library to call the configured OpenAI-compatible `/chat/completions` endpoint (for example, DeepSeek, OpenAI, or a self-hosted server).

```python
from offlook.core import OpenAiCompatibleProvider, run_instruction, default_tools
provider = OpenAiCompatibleProvider("https://api.deepseek.com", "your-key", "deepseek-chat")
result = run_instruction("List PDF files in D:/Docs", provider=provider, tools=default_tools())
print(result.answer)
for step in result.steps:
    print(step.name, step.arguments, step.result, step.error)
```

`run_instruction` is synchronous; call it from a worker, never a Tk callback. Running it (or clicking **Run with AI** in the GUI) sends the instruction to the configured service. Subsequent requests may include tool results such as paths, filenames, and sizes. The tools `list_files`, `filter_files`, `move_files`, `copy_files`, and `organize_by_kind` validate local drive-letter paths and return bounded, JSON-serializable results. Move, copy, and organize operations can change local files. Use a custom `AiToolRegistry` to limit or extend the operations available to the model, and subclass `AiProvider` to integrate a different API. The GUI saves its API key in plaintext in the local JSON configuration; do not commit or share that file.

## Extend renderers

Define the class in a separate importable module, such as my_renderer.py, not as a local class or in __main__. It must have a no-argument constructor:

```python
from offlook.preview.renderers.base import Renderer
from offlook.preview.models import PreviewData, TextContent
class MyRenderer(Renderer):
    """Example text extension with a bounded, read-only source prefix."""
    def render(self, info, request):
        """Read only a small bounded prefix; do not execute source files."""
        from offlook.preview.renderers._io import open_checked
        with open_checked(info) as stream:
            sample = stream.read(min(1024, request.config.max_file_size_bytes))
        return PreviewData(info, TextContent(sample.decode(info.encoding or 'utf-8', errors='replace')))
```

Import MyRenderer in the entry point, create a registry with `registry = default_renderers()`, call `registry.register(FileKind.TEXT, MyRenderer, replace=True)`, and pass that same registry to launch_preview(renderers=registry). Import FileKind from offlook.core and default_renderers from offlook.preview.registry. Keep the preview call inside the main guard. Disabled extensions and oversized media still pass through the central safety routing.
RenderRequest's max_width/max_height are target dimensions in physical pixels. PreviewData.content can be TextContent, TableContent, RasterContent, or MetadataContent. Raster output is limited to 4,096 pixels per edge and 8,388,608 pixels total; rgba must contain exactly width × height × 4 bytes. Do not pass Tk/PIL/COM handles. See each class's English docstring for all fields and limits.

## System integration and errors

`StartupManager` changes the current user's sign-in startup setting only when explicitly toggled. The PATH service `add_offlook_to_user_path()` appends only the current installation's Scripts directory and never changes the machine PATH. Closing the resident main window hides it only when the system tray is available; exiting releases resources. `--background` does not open a console.
`OffLookError` subclasses include `ConfigError`, `FileAccessError`, `PreviewError`, `HotkeyError`, `ExtensionError`, `ConversionError`, and `AiError`. CLI exit codes are `0` for success, `1` for preview failure, `2` for usage, configuration, platform, or initialization failure, and `130` for an interruption in the Tk event loop. The search-shortcut diagnostic exits with `0` on Ctrl+C. The background process is not a permission sandbox; third-party callbacks must enforce the offline boundary themselves.
