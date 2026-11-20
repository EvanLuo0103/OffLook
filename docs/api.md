# OffLook API quick start

Minimal interfaces for contributors. All operations must stay offline. Do not read files or run time-consuming work in Tk callbacks. External plugins are not automatically discovered or executed.

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

`filter_files` is the multi-select companion: pass a collection of `kinds` and/or
`extensions` to match any of several categories at once.

```python
from offlook.core import FileKind, filter_files
results = filter_files("C:/Documents", kinds=[FileKind.PDF, FileKind.IMAGE])
```

FileInfo contains path, kind, size_bytes, modified_time_ns, extension, encoding, and encoding_confidence. Detection synchronously reads up to 64 KiB and accepts only local regular files. Kinds are image/text/markdown/pdf/code/csv/document/binary; document and binary classifications display metadata rather than parsed contents.

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
| convert_hotkey | Alt+C; conversion wheel shortcut |
| convert_mode | auto; also text (text-only) and office (require LibreOffice) |
| always_on_top | False |
| supported_extensions | Tuple of supported extensions; an empty collection shows metadata only |
| ai_enabled / ai_base_url / ai_api_key / ai_model | False / https://api.deepseek.com / "" / deepseek-chat |
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

Conversion runs locally with Pillow and pypdfium2, plus optional LibreOffice
and document backends. `convert_file` converts one source; `convert_files`
converts several and, when the target is PDF and every source is an image,
combines them into one document. Outputs are written next to the source (or into
the directory you pass) and never overwrite existing files.

```python
from offlook.core import convert_file, convert_files, reachable_targets, target_formats, normalize_mode
print(target_formats())                      # every canonical target suffix
print(reachable_targets(["a.png"]))          # targets that source can actually reach
outcome = convert_file("a.png", "pdf")
print(outcome.outputs)
```

`convert_file`/`convert_files`/`reachable_targets` accept a `mode` argument:
`"auto"` (default) uses LibreOffice for high-fidelity document conversion when it
is installed and falls back to text-only; `"text"` forces text-only output; and
`"office"` requires LibreOffice. For presentations, `"text"` offers PDF/TXT/Word
from slide text while `"office"` also renders slides to PNG/JPEG and produces a
layout-preserving PDF.

```python
outcome = convert_file("deck.pptx", "pdf", mode="office")  # requires LibreOffice
```

Word/Excel/PowerPoint text extraction uses the optional `python-docx`,
`openpyxl`, and `python-pptx` packages and raises a clear `ConversionError` when
they are missing. Safe file management is in `offlook.core.file_ops`:

```python
from offlook.core import move_files, organize_by_kind, FileKind
results = move_files(["a.pdf"], "C:/Archive")            # archive files
results = organize_by_kind("C:/Docs", "C:/Archive", kinds=[FileKind.PDF])
```

## AI assistant port

The assistant is opt-in. It is provider-neutral; the built-in
`OpenAiCompatibleProvider` talks to any OpenAI-compatible `/chat/completions`
endpoint (DeepSeek, OpenAI, and many self-hosted servers) using only the
standard library.

```python
from offlook.core import OpenAiCompatibleProvider, run_instruction, default_tools
provider = OpenAiCompatibleProvider("https://api.deepseek.com", "your-key", "deepseek-chat")
result = run_instruction("move all PDFs in D:/Docs to D:/Archive", provider=provider, tools=default_tools())
print(result.answer)
for step in result.steps:
    print(step.name, step.arguments, step.result, step.error)
```

`run_instruction` runs synchronously on the caller's thread — call it from a
worker, never a Tk callback. The built-in tools are `list_files`, `filter_files`,
`move_files`, `copy_files`, and `organize_by_kind`; each validates local
drive-letter paths and returns bounded, JSON-serializable results. Subclass
`AiProvider` to support non-OpenAI APIs, and build a custom `AiToolRegistry` to
expose your own local operations. No network request is made unless the
assistant is explicitly run.

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

StartupManager changes the current user's sign-in startup setting only when explicitly toggled. The PATH service add_offlook_to_user_path() appends only the current installation's Scripts directory and never changes the machine PATH. Closing the main window hides it to the system tray; exiting releases resources. --background does not open a console.
OffLookError subclasses are ConfigError, FileAccessError, PreviewError, HotkeyError, and ExtensionError. CLI exit codes are 0 for success, 1 for file failures, 2 for argument/configuration failures, and 130 for Ctrl+C. The background process is not a permission sandbox; third-party callbacks must enforce the offline boundary themselves.
