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
| hotkey_enabled | True; shared enable gate for Preview, Search files, and Git comparison |
| hotkey | Ctrl+Space; Preview shortcut |
| search_hotkey | Ctrl+Q; prepares a local folder for Search files without starting a search |
| diff_hotkey | Ctrl+Alt+D; Git comparison shortcut |
| always_on_top | False |
| supported_extensions | Tuple of supported extensions; an empty collection shows metadata only |

The three combinations are canonicalized with `parse_hotkey` and must be pairwise distinct even when `hotkey_enabled` is false. Invalid syntax raises `ConfigError` with its `HotkeyError` cause; duplicate errors name both conflicting fields. Missing shortcut fields in old JSON use defaults without rewriting the file; existing collisions are configuration errors, not silently reset. These combinations are defaults, not permanently reserved keys.

The resident GUI's **Enable global shortcuts** switch immediately persists the shared gate. Its Preview / Search files / Git comparison selector maintains separate drafts; **Apply** saves only the selected key. While enabled, a replacement is registered before saving, and the old active key remains on registration or persistence failure. While disabled, Apply only saves. External updates reconcile only shortcut fields and the shared gate; other settings do not rebind keys. Each action registers independently, and statuses distinguish configured keys from active registrations. An external cross-action swap requires an intermediate unused combination rather than an unregister-first swap. `launch_preview` and the single-file CLI command register no global shortcuts.

`offlook.ui.help.show_help(parent, *, shortcuts)` creates the offline Help window; `update_help_shortcuts(window, *, shortcuts)` refreshes its text in place without focusing it and preserves its scroll position. Both accept a mapping with `preview`, `search`, and `diff` keys containing the rendered registration statuses.

`py -m offlook --config '<path>' diagnose-search-shortcut` loads the specified config before creating only the configured search listener and Explorer selection provider; it creates no GUI. It tests `search_hotkey` even with the shared gate disabled, without saving settings. Release that key in the main app and other instances first. Ctrl+C exits the diagnostic with code 0; invalid or missing explicit config exits with code 2.

`events.subscribe(topic, callback)` returns an unsubscribe function. The callback receives Event(topic, payload) synchronously on the publishing thread.

| topic | payload |
| --- | --- |
| config.changed | config |
| preview.requested / preview.closed | path |
| preview.opened | file_info, once for the first frame |
| preview.failed | path, code, message |

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
