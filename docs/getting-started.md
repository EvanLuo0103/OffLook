# Getting started with OffLook

## 1. Download and install

Install 64-bit Python 3.11–3.15 for Windows, including pip, Python Launcher, and Tcl/Tk.
On GitHub, click **Code → Download ZIP**, extract the archive, and open the folder containing pyproject.toml. Type powershell in File Explorer's address bar and press Enter.

Run these commands in order; no virtual environment is needed:

```powershell
py -m pip install --user --only-binary=:all: -r requirements.txt
py -m pip install --user --only-binary=:all: -e .
py -m offlook
```

The first command installs dependencies, the second installs OffLook itself (and also installs dependencies automatically), and the third opens the main window. The initial installation downloads packages; subsequent previews do not need a network connection. Do not move or delete the project folder after installation.

## 2. Set up PATH in one click

Click **Add to PATH** in the main window. After the success or already-present message, reopen PowerShell; if necessary, close and reopen all of Windows Terminal.

```powershell
offlook --version
offlook preview '.\README.md'
```

Only the current user's installation directory is added; administrator privileges are not required. If another offlook version takes precedence, the main window reports the conflict. You can still use `py -m offlook` to launch the version installed for this Python. Existing terminals do not update automatically.

## 3. Preview files

Click **Choose file**, or replace the README path in the CLI example with an existing local file. Quote paths that contain spaces.

- Read text, Markdown, code, and CSV directly. Images retain their aspect ratio, and PDFs support page navigation.
- Esc, unmodified Space, or X closes the preview. **Always on top** applies only to the current preview window.
- Unsupported formats show the filename, size, full path, timestamps, attributes, and type icon. External thumbnail providers are not used.
- Defaults are 10 MiB and a 5-second timeout. Oversized media is not decoded, and text shows only a prefix. Images and PDFs refresh to match the window's physical pixel size, up to 4,096 pixels per edge and 8,388,608 pixels total. Small source images are not enlarged.

The **Search files** card searches a selected local folder and its subfolders without reading file contents. Enter an optional filename fragment, choose a document type, and click **Search**; it includes common Word (`.doc`, `.docx`), Excel (`.xls`, `.xlsx`), PowerPoint, and OpenDocument files. **Other / unknown** finds extensions outside the listed categories. Double-click a result to preview it. Links and network folders are not traversed.

In File Explorer, select one local folder, or open a local folder with nothing selected, and press the **Search files** shortcut (default: **Ctrl+Q**). OffLook loads that folder, scrolls the Search files card into view, and focuses the filename field. It does not search until you click **Search**. A selected regular file or multiple items produces an error; OffLook does not silently use a file's parent folder.

The separate **Git comparison** card compares a tracked text file with its latest committed Git version. Click **Compare with Git HEAD**, or select the file in File Explorer and press the **Git comparison** shortcut (default: **Ctrl+Alt+D**). The comparison window highlights added, deleted, and modified lines. Git comparison supports UTF-8 text files up to 2,000,000 bytes.

To diagnose the configured Search files shortcut without opening the GUI, first exit the main app and any other instance using that key, then run:

```powershell
py -m offlook diagnose-search-shortcut
py -m offlook --config '<path>' diagnose-search-shortcut
```

Use the second form with your actual configuration path to test a custom key. The diagnostic prints the configured combination, reports registration and detection, and checks the selected local folder (or the current local folder when nothing is selected). It keeps listening after selection errors. It tests the saved search key even when **Enable global shortcuts** is off, without changing the file or switch; Ctrl+C stops it with exit code 0. An explicitly specified missing or invalid configuration reports an error and exits with code 2 rather than falling back to defaults.

## 4. Customize global shortcuts

Keep OffLook running, select one file in File Explorer or on the desktop, and press the **Preview** shortcut (default: **Ctrl+Space**) to preview it. Pressing its shortcut again over that preview closes it. Search files and Git comparison have separate configurable keys; the three combinations above are defaults, not reserved keys.

In **Shortcut settings**, choose exactly one action: **Preview**, **Search files**, or **Git comparison**. Click **Record shortcut**, press a new combination inside OffLook, then click **Apply** to save only that action's key. Each action has its own draft, so switching away and back preserves completed edits without saving them. Esc cancels recording; switching actions also cancels unfinished recording and restores its prior draft. **Reset default** changes only the selected draft and also requires **Apply**. Recording an already-active key over the main window captures it without executing its feature.

**Enable global shortcuts** applies immediately to all three actions, independently of the selected-key Apply button. Disabling releases every global key without disabling manual preview, search, or comparison controls. Enabling attempts all three saved keys independently; an occupied key makes only that action **Unavailable**. Controls are temporarily disabled while registrations settle.

Shortcuts require Ctrl or Alt (or both), optionally Shift, and A–Z, 0–9, Space, or F1–F11. The Windows key, F12, and reserved combinations such as Alt+F4 and Alt+Space are not supported. All three saved combinations must be different, even while global shortcuts are disabled. A default key can be assigned to a different action after its previous owner is saved with a distinct key.

The cards and open Help window show actual active keys, or **Disabled**, **Registering**, or **Unavailable** with the configured key and reason. If registration or saving fails, the old active key remains and the proposed draft stays available for retry. Release an occupied key in the other application, then click Apply again, or choose a different combination. If external configuration changes request a swap of active keys, use an intermediate unused combination to release the old key; OffLook does not silently unregister both actions to swap them.

Settings are saved to `%LOCALAPPDATA%\OffLook\config.json` by default, or to the configuration file explicitly specified on the CLI. Older files missing shortcut fields use their defaults without being rewritten just by loading. A file with invalid or duplicate combinations is an explicit configuration error; correct the named fields rather than expecting a silent reset. The single-file `preview` CLI command does not register global shortcuts.

## 5. Background mode, startup, and Help

The main window's X button and **Hide to tray** do not exit OffLook. Double-click the OffLook icon in the notification area to restore it. Select **Exit** to close it completely.
Enable **Start when signing in to Windows** to launch in the background the next time the current user signs in; clear it to disable startup. Avoid running multiple background instances.

```powershell
py -m offlook --background
```

The **Help** button or F1 opens the offline guide with live status for all three shortcuts. If a shortcut does not respond, check its status, that OffLook is running, and that File Explorer is in the foreground. Preview and Git comparison require one selected file; Search files accepts one selected folder or the current folder with nothing selected. An input method may reserve a combination; change it or use the manual controls.

## 6. Convert, filter, and use AI

***Convert files**: select one or more files in File Explorer and press **Alt+C** (or change it in **Shortcut settings**) to open the conversion chooser, then select a target format. Alternatively, click **Choose files to convert**. Images convert between PNG, JPEG, BMP, GIF, TIFF, WebP, and ICO, and to PDF; PDFs convert to image formats; text, Markdown, code, and CSV convert to PDF, TXT, or Word. Word, Excel, and PowerPoint files can convert to PDF/TXT/CSV/images where supported. Legacy `.doc`, `.xls`, and `.ppt` files require LibreOffice for PDF conversion. HTML files convert to PDF or TXT, and ZIP archives can be extracted locally.

The **Quality** selector controls document fidelity: `auto` uses LibreOffice when installed, `text` produces text-only output, and `office` requires LibreOffice. Output files are placed next to the source and existing files are never overwritten.

**Filter files**: in the **Filter files** card, choose a folder and check any combination of formats, then click **Apply filter** to list matching files recursively.

**AI assistant**: enable it, enter an OpenAI-compatible base URL (e.g. `https://api.deepseek.com`), a model (e.g. `deepseek-chat`), and your API key, then click **Save AI settings**. Type an instruction such as "move all PDF files in D:\Docs to D:\Archive" and click **Run with AI**. This is the only network feature: requests go only to the endpoint you configured, and the assistant acts on local files through OffLook's list/filter/move/copy/organize tools.

## Optional: manual PATH troubleshooting
If the UI is unavailable, run the same service from the project root:

```powershell
py -c "from offlook.platforms.windows_environment import add_offlook_to_user_path; print(add_offlook_to_user_path())"
```

This also changes only the user PATH. Reopen your terminal afterward. If policy prevents the change, an error is reported: do not elevate privileges or modify the system PATH. Continue using `py -m offlook` instead.
