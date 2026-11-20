# OffLook Python API reference

Interfaces for Python integrations and contributors. Do not read files or run time-consuming work in Tk callbacks. External plugins are not automatically discovered or executed. For GUI setup and command syntax, see the [user guide](getting-started.md).

## Create a context and identify files

```python
from offlook.core import create_context, FileTypeDetector
context = create_context()
info = FileTypeDetector().detect("README.md")
print(info.kind.value, info.path, info.size_bytes)
```

`FileInfo` contains `path`, `kind`, `size_bytes`, `modified_time_ns`, `extension`, `encoding`, and `encoding_confidence`. Detection synchronously reads up to 64 KiB and accepts only local regular files. A file's detected kind does not guarantee that its contents can be previewed.

## Search and filter files

To search a local folder recursively without reading file contents:

```python
from offlook.core import FileKind, find_files
results = find_files("C:/Documents", filename="report", kind=FileKind.PDF)
```

`filter_files` is the multi-select companion. A file must match the optional case-insensitive `filename` substring **and** each nonempty filter group: any kind in `kinds` **and** any suffix in `extensions`. Within a group, values are alternatives. An empty group imposes no restriction. Both functions classify by extension without reading contents, skip symbolic links, and skip inaccessible subfolders.

Both GUI search views call `filter_files`. See the [command-line reference](getting-started.md#7-command-line-reference) for the distinct `search` and `filter` command syntax.

```python
from offlook.core import FileKind, filter_files
results = filter_files("C:/Documents", kinds=[FileKind.PDF, FileKind.IMAGE])
```

## Compare two local files

```python
from offlook.core import compare_files

comparison = compare_files('before.md', 'after.docx')
print(comparison.changed)
for line in comparison.lines:
    print(line.kind, line.old_line, line.new_line, line.text)
```

`compare_files(old_path, new_path, *, max_bytes=2_000_000)` reads and parses both local files synchronously without rewriting them or creating intermediate files. Run it off the Tk thread. It compares only the two supplied paths, not Git HEAD. The CLI counterpart is [`compare`](getting-started.md#7-command-line-reference).

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

Call from the main thread; an exit code is returned when the window closes. Do not launch this application inside a host with an existing Tk instance. The GUI uses a terminable spawn process per request and ignores stale responses. Explorer selection still runs separately from rendering, without loading the renderer registry in the selection child.

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
| hotkey_enabled | True; shared gate for all five global shortcuts |
| hotkey | Ctrl+Space; Preview shortcut |
| diff_hotkey | Ctrl+Alt+D; Compare files shortcut |
| convert_hotkey | Alt+C; opens the **Convert to** dropdown dialog |
| filter_hotkey | Ctrl+Alt+F; opens only the Search & filter quick window for a valid Explorer folder, without scanning |
| ai_hotkey | Ctrl+Alt+Shift+A; opens only the AI assistant quick window, without requiring a selection or starting a run |
| convert_mode | `auto`; also `text` and `office`. Backend choice depends on the source and target. |
| always_on_top | False |
| supported_extensions | Tuple of supported extensions; an empty collection shows metadata only |
| ai_enabled / ai_base_url / ai_model | `False` / `https://api.deepseek.com` / `deepseek-chat`. `ai_enabled` is a saved preference, not a runtime gate. Keys are no longer fields on `PreviewConfig`. |
| language | en; also zh. Selects the interface language; `offlook.ui.i18n.tr` reads it. |

On Windows, save a key with `context.config.update(config, persist=True, ai_key_action='replace', ai_key=key)`. Use `ai_key_action='clear'` to remove it. Ordinary config loads do not read the vault or migrate legacy keys. A key is bound to its profile path and endpoint; pass a new key when changing endpoints.

All five combinations are canonicalized with `parse_hotkey` and must be distinct even when `hotkey_enabled` is false. Loading an older configuration does not rewrite it. The former main-window `search_hotkey` is ignored. For a missing `filter_hotkey`, the first unused candidate is chosen from `Ctrl+Alt+F`, `Ctrl+Alt+Shift+F`, `Ctrl+Alt+G`, `Ctrl+Alt+Shift+G`, `Ctrl+Alt+J`, `Ctrl+Alt+Shift+J`. Then, if `ai_hotkey` is missing, the first unused candidate is chosen from `Ctrl+Alt+Shift+A`, `Ctrl+Alt+A`, `Ctrl+Alt+Shift+I`, `Ctrl+Alt+I`, `Ctrl+Alt+Shift+K`, `Ctrl+Alt+K`. Existing explicit bindings for these five actions are preserved; invalid or duplicate values raise `ConfigError`. OS registration conflicts do not trigger a different binding.

In a running main window, `config.changed` reconciles the shortcut fields and shared gate; external JSON edits are not watched. `launch_preview` does not register global shortcuts. See [shortcut settings](getting-started.md#4-customize-global-shortcuts) for recording and registration behavior.

`offlook.ui.help.show_help(parent, *, shortcuts)` creates the offline Help window; `update_help_shortcuts(window, *, shortcuts)` refreshes it without focusing it and preserves its scroll position. OffLook supplies `preview`, `diff`, `convert`, `filter`, and `ai` with their rendered registration statuses. An omitted `ai` entry is shown as not registered.

`events.subscribe(topic, callback)` returns an unsubscribe function. The callback receives Event(topic, payload) synchronously on the publishing thread.

| topic | payload |
| --- | --- |
| config.changed | config |
| preview.requested / preview.closed | path |
| preview.opened | file_info, once for the first frame |
| preview.failed | path, code, message |

## Convert and manage files

Conversion runs locally using Pillow and pypdfium2, with document backends where needed. `convert_file(source, target, directory=None, mode="auto")` returns one `ConversionOutcome` with `source` and `outputs` (a tuple of output paths). `convert_files(sources, target, directory=None, mode="auto")` returns a tuple of outcomes. Multiple images targeting PDF produce one combined document named after the first source and one outcome. Other batches convert files individually.

By default, each output goes next to its source (the first source for a combined PDF); pass `directory` to choose a different location. Existing names get numbered alternatives. This naming is not a guarantee against collisions between concurrent writers.

```python
from offlook.core import convert_file, reachable_targets, target_formats

print(target_formats())                      # recognized target tokens, in dialog order
print(reachable_targets(["a.png", "b.jpg"]))  # targets shared by the selection
outcome = convert_file("a.png", "pdf")
print(outcome.outputs)
```

`target_formats()` lists tokens, not implemented conversions for every source: `.xlsx` does not promise Excel output, and `.extract` unpacks a ZIP into a new folder. `reachable_targets(sources, mode="auto")` returns the shared targets offered by the dialog, not a comprehensive list of direct conversions or a backend availability check.

`convert_file`, `convert_files`, and `reachable_targets` accept `mode="auto"`, `"text"`, or `"office"`. See [conversion formats and backends](getting-started.md#convert-files) for the source/target matrix and direct-call exception for legacy Office files.

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

The [AI page and quick window](getting-started.md#ai-file-assistant) share one task; neither opening a window nor saving connection settings invokes the provider.

```python
from offlook.core import OpenAiCompatibleProvider, run_instruction, default_tools
provider = OpenAiCompatibleProvider("https://api.deepseek.com", "your-key", "deepseek-chat")
result = run_instruction("List PDF files in D:/Docs", provider=provider, tools=default_tools())
print(result.answer)
for step in result.steps:
    print(step.name, step.arguments, step.result, step.error)
```

`run_instruction` is synchronous; call it from a worker, never a Tk callback. Instructions and some tool results can reach the configured service. `default_tools()` exposes only `list_files` and `filter_files`. `default_tools(approve_write=callback)` also exposes the built-in move, copy, and organize tools; the trusted callback receives a frozen plan and must approve each operation explicitly. The default write tools never overwrite files. A custom `AiToolRegistry` remains a trusted extension, and an `AiProvider` subclass can integrate a different API.

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

`StartupManager` manages the current user's sign-in startup setting. `add_offlook_to_user_path()` adds the current installation directory (or Python Scripts directory) to the user PATH. `remove_offlook_from_user_path()` removes it only if OffLook recorded adding it for that installation. For command behavior and exit codes, see the [command-line reference](getting-started.md#7-command-line-reference).

`OffLookError` subclasses include `ConfigError`, `FileAccessError`, `PreviewError`, `HotkeyError`, `ExtensionError`, `ConversionError`, and `AiError`.
