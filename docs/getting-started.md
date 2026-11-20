# OffLook user guide

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

OffLook has not been published to PyPI; do not install another package with the same name.

Use the sidebar to switch between **File tools**, **Search & filter**, **AI file assistant**, and **Settings**. Switching pages does not clear forms or results.

Use **中文 / English** to change the interface language; the choice is saved immediately. In scrollable windows, lists and text areas scroll their own contents first. Scrolling over the **Quality** dropdown can change its value.

## 2. Set up PATH in one click

Open **Settings → System integration** and click **Add to PATH**. After the success or already-present message, reopen PowerShell; if necessary, close and reopen all of Windows Terminal.

```powershell
ol --version
ol preview '.\README.md'
```

Only the current user's installation directory is added; administrator privileges are not required. If another offlook version takes precedence, the main window reports the conflict. You can still use `py -m offlook` to launch the version installed for this Python. Existing terminals do not update automatically.

`ol` and `offlook` run the same CLI. If you installed OffLook before `ol` was added, rerun the editable install command above to generate `ol.exe`. If PowerShell resolves `ol` to another command, use `Get-Command ol -All` to check the conflict, or use `offlook` instead.

## 3. Preview files

Click **Choose file**, or replace the README path in the CLI example with an existing local file. Quote paths that contain spaces.

- Read text, Markdown, code, and CSV directly. Markdown uses lightweight formatting. Images retain their aspect ratio and show only the first frame. PDFs support page navigation; password-protected PDFs are not supported.
- Esc, unmodified Space, or X closes the preview. **Always on top** applies only to the current preview window.
- Unsupported formats, including DOCX, show metadata such as filename, size, full path, timestamps, attributes, and type icon. External thumbnail providers are not used.
- Defaults are 10 MiB and a 5-second timeout. Oversized media shows metadata only, text may be truncated, and empty text may show **Empty file**. Images and PDFs refresh to match the window's physical pixel size, up to 4,096 pixels per edge and 8,388,608 pixels total. **Fit** does not enlarge small source images; manual zoom is separate.

Previews and comparisons accept local regular files. Shortcut selection rejects network paths, reparse points, and cloud-recall paths. Previewing does not execute code or CSV formulas.

### Search and filter files

On **Search & filter**, choose a local folder, optionally enter a case-insensitive filename fragment, and check any number of file types. A file must match the name and any checked type; no checks means all types. Click **Search** or press Enter in the filename field. The scan includes subfolders, skips links and inaccessible directories, and does not read file contents. Double-click a result or select it and press Enter to preview.

In File Explorer, select one local folder or leave nothing selected inside a local folder. **Ctrl+Q** opens the main **Search & filter** page, fills the folder, and focuses the filename field. **Ctrl+Alt+F** instead opens only the quick window, with a fixed folder and the same filename and type filters. Neither shortcut scans automatically. One selected regular file or multiple items is an error, not a request to use the parent folder.

If the main-window key does not work, see [Diagnose the search shortcut](#diagnose-the-search-shortcut).

### Compare two files

- In **File comparison**, click **Compare two files**. In the native Windows Open dialog, hold Ctrl and select exactly two files from the same folder, then click **Open**. OffLook assigns Old and New by path order, not click order; use **Swap files** to reverse them. **Cancel** closes the picker without comparing.
- In File Explorer or on the desktop, select exactly two local files and press **Ctrl+Alt+D**, the default **Compare files** shortcut. A folder or extra item in the selection prevents comparison. The shortcut assigns Old and New by path order, not click order. If OffLook is hidden to the tray, the comparison opens without restoring the main window.

Compare UTF-8 or Unicode text with a byte-order mark: TXT, Markdown, RST, CSV/TSV, logs, code, or even files without an extension. Markdown and HTML are compared as source text. OffLook can also compare body paragraphs and table text in Word `.docx` files, including against plain text; it does not compare Word layout, images, or headers and footers. DOCX line numbers refer to extracted text, not pages. Legacy `.doc`, PDFs, and other binary documents are not supported. The default limits are 2,000,000 bytes and 20,000 lines per file; larger inputs produce an error rather than a partial comparison. No Git installation, repository, or GitHub account is required.

The result opens in **Split** view (old on the left, new on the right). Switch to **Unified** to see both in one list. Red `-` lines are removals, green `+` lines are additions, and paired edits highlight the changed text within each line. A changed pair counts as one removal and one addition. OffLook shows nearby unchanged lines around each change; click **Show … unchanged lines** to reveal a collapsed section. A change to the final newline still counts as an edit to the last line; the `\ No newline at end of file` notice itself is not counted. Click **Swap files** to compare in the opposite direction. Esc or X closes the result without exiting OffLook.

## 4. Customize global shortcuts

Keep OffLook running and select one local file in File Explorer or on the desktop to use **Preview** (**Ctrl+Space**). Pressing its shortcut again over that preview closes it. Other defaults: **Search & filter (main window)** (**Ctrl+Q**), **Search & filter (quick window)** (**Ctrl+Alt+F**), **Compare files** (**Ctrl+Alt+D**), **Convert files** (**Alt+C**), and **AI file assistant** (**Ctrl+Alt+Shift+A**, no file selection). All six are configurable.

In **Settings → Shortcut settings**, choose the action to change. Click **Record shortcut**, press a new combination inside OffLook, then click **Apply** to save only that action's key. Each action has its own draft. Esc, switching actions, or leaving the settings page cancels unfinished recording and restores its prior draft. **Reset default** changes only the selected draft and also requires **Apply**. Recording an active key captures it without executing the feature.

**Enable global shortcuts** applies immediately to all actions, independently of the selected-key Apply button. Disabling releases every global key without disabling manual controls. Enabling attempts the saved keys independently; an occupied key makes only that action **Unavailable**. Controls are temporarily disabled while registrations settle.

Shortcuts require Ctrl or Alt (or both), optionally Shift, and A–Z, 0–9, Space, or F1–F11. The Windows key, F12, and reserved combinations such as Alt+F4 and Alt+Space are not supported. All saved combinations must be different, even while global shortcuts are disabled. A default key can be assigned to a different action after its previous owner is saved with a distinct key.

The cards and Help show actual registrations, independent of the saved keys. If registration or saving fails, the old active key remains and the draft is kept. Release an occupied key before retrying. OffLook does not watch its JSON file: exit before editing it from another process and restart to load changes. A swap of live registrations through in-process settings requires an intermediate unused combination.

Settings are saved to `%LOCALAPPDATA%\OffLook\config.json` by default, or to the explicit CLI configuration file. If an old configuration lacks `filter_hotkey` or `ai_hotkey`, OffLook picks an unused default from the [candidate lists](api.md#configuration-and-events) without changing saved keys or rewriting the file. Explicitly invalid or duplicate combinations are errors. The `preview` and `filter` CLI commands do not register global shortcuts.

## 5. Background mode, startup, and Help

The main window's X button and **Hide to tray** hide OffLook only when the system tray is available. Double-click the OffLook icon in the notification area to restore it. Select **Exit** to close it completely.
Enable **Start when signing in to Windows** to launch in the background the next time the current user signs in; clear it to disable startup. Avoid running multiple background instances.

```powershell
py -m offlook --background
```

The **Help** button or F1 opens the offline guide with live shortcut status. Reopen Help after switching languages. If a key does not respond, check its status and confirm OffLook is running. See [Search and filter files](#search-and-filter-files) for required Explorer selection. The AI quick window works without File Explorer or a selection. An input method may reserve a combination; change it or use the manual controls.

### Diagnose the search shortcut

Exit OffLook and any other instance using the search key, then run:

```powershell
py -m offlook diagnose-search-shortcut
py -m offlook --config '<path>' diagnose-search-shortcut
```

Use the second form with your actual configuration path to test a custom key. The diagnostic runs without opening a window and reports registration, key detection, and the selected Explorer folder (or the current local folder when nothing is selected). It keeps listening after selection errors and tests the saved shortcut even when **Enable global shortcuts** is off, without changing settings. Ctrl+C exits with code 0. A missing or invalid explicit configuration returns 2.

## 6. Convert, filter, and use AI

For filtering in the app, see [Search and filter files](#search-and-filter-files); for terminal use, see the [`filter` examples](#filter-examples).

### Convert files

**Convert files**: select one or more files in File Explorer and press the default **Alt+C**, or click **Choose files to convert** in **File tools**. The shortcut opens only the **Convert to** dialog; it does not restore the main window. Choose a format and click **Convert** or press Enter. **Cancel**, Esc, or X dismisses the chooser before conversion. Once started, progress and the result (output paths or an error) stay in the same dialog; click **Close** when finished. Multiple images targeting PDF become pages of one PDF; other files are converted individually. OffLook writes outputs next to the source and adds a number if an output name already exists.

Set **Quality** before opening the dialog. The formats and backends below determine which modes are useful. An offered target may still fail if its backend is missing. `python-docx` is installed with OffLook; `docx2pdf`, `openpyxl`, and `python-pptx` are optional packages.

| Source | Available outputs and requirements |
| --- | --- |
| Common images | PNG, JPEG, BMP, GIF, TIFF, WebP, ICO, or PDF. |
| PDF | PNG, JPEG, BMP, or TIFF. |
| Text, Markdown, code, and CSV | PDF, TXT, or Word (`.docx`). |
| Word (`.docx`) | TXT extracts paragraphs. For PDF, `auto` uses Microsoft Word and `docx2pdf` with no automatic fallback; `text` uses paragraphs only; `office` uses LibreOffice. |
| Excel (`.xlsx`) | CSV or TXT via `openpyxl`. PDF requires LibreOffice in `auto` or `office` mode. |
| PowerPoint (`.pptx`) | The dialog offers PDF/TXT/DOCX in `text`; PDF/PNG/JPEG/TXT in `office`; and PDF/PNG/JPEG/TXT/DOCX in `auto`. TXT and DOCX use `python-pptx`; PNG/JPEG require LibreOffice. PDF in `auto` uses LibreOffice when available, otherwise slide text. |
| Legacy Office (`.doc` / `.xls` / `.ppt`) | PDF via LibreOffice in `auto` or `office` mode. |
| HTML | TXT extracts readable text; PDF uses LibreOffice in `office` mode or when available in `auto`, and otherwise uses extracted text. |
| ZIP | **Extract archive** unpacks the ZIP to a new folder. The CLI uses `--to extract`; the Python API accepts `.extract`. |

Direct CLI and Python conversion can convert legacy Office files to PDF with LibreOffice even in `text` mode; the GUI does not offer that combination.

### AI file assistant

**AI file assistant**: enter an OpenAI-compatible **Base URL** (for example, `https://api.deepseek.com`), a **Model** (for example, `deepseek-chat`), and your **API key**, then click **Save AI settings**. Saving does not contact the service. The key is saved in plaintext in the local JSON configuration; keep that file private. The **Enable AI assistant** checkbox is a saved preference, not a runtime access control.

Press **Ctrl+Alt+Shift+A** to open the AI quick window without restoring or switching the main window. No file selection is needed. Both views share the instruction, progress, and last result. The quick window uses the saved connection settings and can close during a run without cancelling it.

To contact the service, enter an instruction such as `List PDF files in D:\Docs` and click **Run with AI**. Your instruction is sent to the configured service; subsequent requests may include tool results such as paths, filenames, and sizes. The assistant uses OffLook's local tools to list, filter, move, copy, or organize files. Use a service you trust, and start with a listing if you do not want to change files.

## 7. Command-line reference

Run `ol <command> --help` for exact options. The `ol` and `offlook` commands require the installation's Scripts directory on PATH; `py -m offlook` also works without that PATH change. Square brackets below denote optional operands, not literal characters. Put global options (`--config PATH`, `--background`, `--version`) before the command. Quote paths with spaces.

| Command | Behavior |
| --- | --- |
| No command; `--background` | Open the main window, or start a resident instance hidden to the tray. A successful detached launch does not mean that the tray or hotkeys are ready. |
| `preview FILE [--topmost]` | Open one preview without global shortcuts. `--topmost` only applies to this launch. |
| `search [FOLDER] [--name TEXT] [--kind KIND]` | Recursive search by case-insensitive name substring and one category. Omitted folder means the working directory. Outputs absolute paths; no matches is success. |
| `filter [FOLDER] [--name TEXT] [--kind KIND ...] [--ext EXT ...]` | Recursive filter (default folder: working directory). Within each group values are alternatives; all nonempty groups and any name substring must match. `--ext=` matches suffixless files. |
| `filter [FOLDER] --gui [--kind KIND ...]` | Opens only the Search & filter quick window. The folder (default: working directory) is fixed; use the filename field and type checks, then click **Search**. No `--name` or `--ext`. |
| `compare OLD NEW` | Compare in argument order. Unified text output for differences, 0 if identical, 1 if different, 2 on error. DOCX is compared as extracted text, not a patch to a Word file. |
| `convert FILE [FILE ...] --list-targets [--mode MODE]` | List shared format tokens, one per line, without writing files or checking optional backends. |
| `convert FILE [FILE ...] --to FORMAT [--mode MODE] [--output-dir DIR]` | Convert and print absolute output paths. `MODE` is `auto` (default), `text`, or `office`. `extract` unpacks ZIP only. The output directory, if given, must exist; otherwise files are written beside each source, or beside the first source for combined images to PDF. A batch error can leave outputs already written. Direct legacy Office-to-PDF conversion uses LibreOffice even with `--mode text`; the dialog does not offer that mode for legacy files. |
| `copy FILE [FILE ...] --to DIR [--conflict POLICY]`; `move` with the same arguments | Copy or move into an existing directory. Default `rename` numbers conflicts; `skip` preserves the existing file; explicit `overwrite` replaces ordinary files. |
| `organize FOLDER --to DIR [--kind KIND ...]` | Move files into category subdirectories of an existing directory **outside** the source tree. Omitting `--kind` includes all categories. |
| `settings show`; `settings set KEY [VALUE ...]` | Read or save preferences and shortcut bindings, excluding AI connection settings. |
| `startup status`; `startup enable`; `startup disable` | Read or change OffLook's current-user sign-in registration. `status` prints `enabled` or `disabled`; this does not indicate whether the program is running. |
| `path add` | Add the installed Scripts directory once to the current user PATH and print the directory. Open a new terminal afterward. Warnings about propagation or another executable taking precedence do not roll back the saved entry. |
| `diagnose-search-shortcut` | Test the saved main-window Search & filter key and Explorer folder selection; stop with Ctrl+C. |

Categories: `image`, `text`, `markdown`, `pdf`, `code`, `csv`, `document`, `binary`. Redirected data uses UTF-8 with LF. Copy, move and organize produce one JSON object per item (`source`, `destination`, `status`, `message`); `status` is `copied`, `moved`, `skipped` or `failed`. A failed item is also reported on stderr and returns 2, even if others succeeded. Otherwise success returns 0; preview rendering failure returns 1 after the window closes. Invalid input, configuration, platform or initialization returns 2. Interrupted commands normally return 130; the shortcut diagnostic returns 0 on Ctrl+C.

`--config PATH` is supported for GUI launch, `preview`, `filter --gui`, `diagnose-search-shortcut`, `settings` and `startup enable`. An explicit config must exist. `settings set` accepts integer `max_file_size_bytes`, numeric `preview_timeout_seconds`, `supported_extensions` (zero or more suffixes; no values disables content renderers), booleans `always_on_top` / `hotkey_enabled` (`true` or `false`), six shortcut keys (`hotkey`, `search_hotkey`, `diff_hotkey`, `convert_hotkey`, `filter_hotkey`, `ai_hotkey`), `convert_mode` (`auto`, `text`, `office`), and `language` (`en`, `zh`). This does not register shortcuts or reload another running instance. Close the GUI before editing settings from the CLI; restart to apply them.

```powershell
py -m offlook search --name started --kind markdown
py -m offlook convert '.\README.md' --list-targets
py -m offlook settings show
py -m offlook startup status
```

Use `py -m offlook path add` if the UI is unavailable. If policy prevents the change, do not elevate or modify the machine PATH; keep using `py -m offlook`.

### Filter examples

```powershell
py -m offlook filter '.\docs' --kind markdown --ext md --name started
py -m offlook filter '.\docs' --gui --kind markdown
```

The first command prints one absolute path per line and succeeds even if there are no matches. The second opens only the quick window with Markdown preselected; enter a filename fragment if needed, then click **Search**. Omit the folder in either command to use the terminal's working directory.
