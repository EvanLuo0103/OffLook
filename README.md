# OffLook

**English** | [繁體中文](README.zh-TW.md)

An offline file previewer for Windows with GUI and CLI interfaces. Previews and file comparisons run locally without a network connection. The optional AI file assistant contacts the service you configure only when you run it.

![OffLook main window (English)](docs/images/main-window-en.png)

Use **中文 / English** to switch the interface language.

## Install and launch

Download and extract the ZIP from GitHub, then open PowerShell in the folder containing pyproject.toml. Requires 64-bit Python 3.11–3.15 for Windows, pip, Python Launcher, and Tcl/Tk.

```powershell
py -m pip install --user --only-binary=:all: -r requirements.txt
py -m pip install --user --only-binary=:all: -e .
py -m offlook
```

Install from this repository, not PyPI, and keep the extracted folder. See [download and install](docs/getting-started.md#1-download-and-install) for detailed setup.

## Quick tour

Keep OffLook running to use the default shortcuts:

| Shortcut | Action |
| --- | --- |
| `Ctrl+Space` | Preview the selected local file in File Explorer or on the desktop. |
| `Ctrl+Q` / `Ctrl+Alt+F` | Open [Search & filter](docs/getting-started.md#search-and-filter-files) in the main window or in an independent quick window, respectively. |
| `Ctrl+Alt+D` | Compare two selected local files. |
| `Alt+C` | Open the conversion dialog for selected files without restoring the main window. |
| `Ctrl+Alt+Shift+A` | Open the AI assistant quick window; no selection is needed. |

Change bindings in **Settings → Shortcut settings**. Press F1 for built-in help and live registration status.

## Command-line examples

Reinstall after updating to get the `ol` command. If it is not found, [add OffLook to PATH](docs/getting-started.md#2-set-up-path-in-one-click) and reopen PowerShell.

```powershell
ol preview '.\README.md'
ol --background
ol search --name report --kind pdf
ol compare before.txt after.docx
ol convert '.\README.md' --to pdf
ol filter '.\docs' --kind markdown
ol filter '.\docs' --gui --kind markdown
```

See the [command-line reference](docs/getting-started.md#7-command-line-reference) for arguments and exit codes, or run `ol --help`.

## Documentation

- [User guide](docs/getting-started.md) — installation, GUI workflows, supported formats, shortcut troubleshooting, and CLI reference.
- [Python API reference](docs/api.md) — configuration, events, file operations, and extension points.

requirements.txt is the single source of runtime dependencies; pyproject.toml defines packaging and entry points. OffLook uses the [MIT license](LICENSE); dependencies retain their respective licenses.
