# OffLook

**English** | [繁體中文](https://github.com/EvanLuo0103/OffLook/blob/main/README.zh-TW.md)

OffLook is an open-source Windows tool for inspecting and working with local files without leaving File Explorer. If you just need to check a report, opening a PDF reader or editor for every candidate slows you down. With OffLook running in the system tray, select a file and press **Ctrl+Space** to take a look, then press **Esc** to return to browsing.

- **Find the right file.** Narrow a folder and its subfolders by part of a filename and one or more file types, then open a preview from the results. Read supported PDFs, images, Markdown, text, code, and CSV without opening a separate viewer for each format.
- **See what changed.** Compare two text or Word (`.docx`) files side by side, including Word against plain text. OffLook highlights text changes without requiring Git or Microsoft Word.
- **Prepare files for sharing.** Combine selected images into one PDF or convert Markdown to PDF. The conversion dialog tells you when a format needs an additional backend before you start.

Use shortcuts and small windows for one-off tasks, or use the `ol` command in PowerShell when you want to repeat a task or pipe results into another command. Preview, search, and comparison run locally without uploading files. The optional AI assistant only contacts the service you configure when you click **Run with AI**; its file tools are read-only by default.

![OffLook main window (English)](https://raw.githubusercontent.com/EvanLuo0103/OffLook/main/docs/images/main-window-en.png)

Use **中文 / English** to switch the interface language.

## Install and launch

**Without Python:** Download the Windows x64 installer from [GitHub Releases](https://github.com/EvanLuo0103/OffLook/releases). Start OffLook from the Start menu. Adding `ol` to your user PATH is optional.

**With Python:** On Windows with 64-bit Python 3.11–3.15, Tcl/Tk, and the Python Launcher, use the following commands once the [PyPI package](https://pypi.org/project/offlook/) is published:

```powershell
py -m pip install --user offlook
py -m offlook
```

Use `offlook[office]` for optional Python conversion backends. Microsoft Word and LibreOffice are separate installs. For another way to get started, see [how to install from source](https://github.com/EvanLuo0103/OffLook/blob/main/docs/getting-started.md#1-download-and-install).

## Quick tour

Keep OffLook running to use the default shortcuts:

| Shortcut | Action |
| --- | --- |
| `Ctrl+Space` | Preview the selected local file in File Explorer or on the desktop. |
| `Ctrl+Alt+F` | Open only the [Search & filter quick window](https://github.com/EvanLuo0103/OffLook/blob/main/docs/getting-started.md#search-and-filter-files). |
| `Ctrl+Alt+D` | Compare two selected local files. |
| `Alt+C` | Open the conversion dialog for selected files without restoring the main window. |
| `Ctrl+Alt+Shift+A` | Open the AI assistant quick window; no selection is needed. |

Change bindings in **Settings → Shortcut settings**. Press F1 for built-in help and live registration status.

## Command-line examples

If `ol` is not found, [add OffLook to PATH](https://github.com/EvanLuo0103/OffLook/blob/main/docs/getting-started.md#2-set-up-path-in-one-click) and reopen PowerShell.

```powershell
ol preview '.\README.md'
ol --background
ol search --name report --kind pdf
ol compare before.txt after.docx
ol convert '.\README.md' --to pdf
ol filter '.\docs' --kind markdown
ol filter '.\docs' --gui --kind markdown
```

See the [command-line reference](https://github.com/EvanLuo0103/OffLook/blob/main/docs/getting-started.md#7-command-line-reference) for arguments and exit codes, or run `ol --help`.

## Documentation

- [User guide](https://github.com/EvanLuo0103/OffLook/blob/main/docs/getting-started.md) — installation, GUI workflows, supported formats, shortcut troubleshooting, and CLI reference.
- [Python API reference](https://github.com/EvanLuo0103/OffLook/blob/main/docs/api.md) — configuration, events, file operations, and extension points.

Base dependencies are listed in `requirements.txt`; packaging, optional extras, and entry points are in `pyproject.toml`. OffLook uses the [MIT license](https://github.com/EvanLuo0103/OffLook/blob/main/LICENSE); dependencies retain their respective licenses.
