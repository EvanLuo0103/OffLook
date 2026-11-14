# OffLook

An offline file previewer for Windows with GUI and CLI interfaces. All files are processed locally, without uploads or external links.

## Install and launch

Download and extract the ZIP from GitHub, then open PowerShell in the folder containing pyproject.toml. Requires 64-bit Python 3.11–3.15 for Windows, pip, Python Launcher, and Tcl/Tk.

```powershell
py -m pip install --user --only-binary=:all: -r requirements.txt
py -m pip install --user --only-binary=:all: -e .
py -m offlook
```

No virtual environment is used. The initial installation downloads dependencies; previews do not require a network connection. OffLook has not been published to PyPI: do not install an unrelated package with the same name. Keep the project folder after installation.

## Main controls

- Click **Choose file** in the main window, or select one file in File Explorer or on the desktop and press the default **Ctrl+Space** shortcut.
- Use **Search files** to choose a local folder, search recursively by filename, and filter by document type, including Word, Excel, and PowerPoint files; double-click a result to preview it.
- In File Explorer, open or select a local folder and press the fixed **Ctrl+Q** shortcut to load that folder into Search files.
- To test `Ctrl+Q` separately, run `py -m offlook diagnose-search-shortcut`; it reports shortcut registration, detection, and selected-folder validation.
- Use **Shortcut settings** to record and apply a new combination. The previous shortcut is kept if registration or saving fails.
- Click **Add to PATH** and reopen PowerShell as instructed to use `offlook preview '.\README.md'`.
- Close a preview with Esc or Space, navigate PDF pages, or keep the current preview on top. Images and PDFs refresh at higher resolution when the window grows.
- Unsupported or disabled formats show a type icon, size, full location, timestamps, and other metadata, not binary contents.
- The main window's X button hides it to the system tray; double-click the tray icon to reopen it. **Exit** closes the application completely. You can also enable startup at sign-in.
- **Help** or F1 opens the built-in guide. See [Getting started](docs/getting-started.md) for full instructions and [API](docs/api.md) for integration interfaces.

```powershell
py -m offlook preview '.\README.md'
py -m offlook --background
```

## Supported formats and limits

Supports text, Markdown, code, CSV, common images, and static PDFs. Markdown uses lightweight formatting, images show only the first frame, and password-protected PDFs are not supported. Defaults are 10 MiB and a 5-second timeout: text is truncated, while oversized media shows metadata only. Output is limited to 4,096 physical pixels per edge and 8,388,608 pixels total; small source images are not enlarged.

Only local regular files are accepted; network paths, reparse points, and cloud-recall paths are rejected. OffLook does not execute code or CSV formulas or invoke third-party thumbnail handlers. The operating system, synchronization software, and other external components are outside its control, so absolute prevention of data leakage cannot be guaranteed. Conversion, classification, AI, search, and diff are not implemented.

requirements.txt is the single source of runtime dependencies; pyproject.toml defines packaging and entry points. OffLook uses the [MIT license](LICENSE); dependencies retain their respective licenses.
