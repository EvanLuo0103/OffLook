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
- Unsupported formats, including DOCX, show metadata such as filename, size, full path, timestamps, attributes, and type icon. External thumbnail providers are not used.
- Defaults are 10 MiB and a 5-second timeout. Oversized media shows metadata only, text may be truncated, and empty text may show **Empty file**. Images and PDFs refresh to match the window's physical pixel size, up to 4,096 pixels per edge and 8,388,608 pixels total. **Fit** does not enlarge small source images; manual zoom is separate.

### Search for files

The **Search files** card searches a selected local folder and its subfolders without reading file contents. Enter an optional filename fragment, choose a document type, and click **Search**; it includes common Word (`.doc`, `.docx`), Excel (`.xls`, `.xlsx`), PowerPoint, and OpenDocument files. **Other / unknown** finds extensions outside the listed categories. Double-click a result to preview it. The scan skips symbolic links and inaccessible subfolders.

In File Explorer, select one local folder, or open a local folder with nothing selected, and press the **Search files** shortcut (default: **Ctrl+Q**). OffLook loads that folder, scrolls the Search files card into view, and focuses the filename field. It does not search until you click **Search**. A selected regular file or multiple items produces an error; OffLook does not silently use a file's parent folder.

To diagnose the configured Search files shortcut without opening the GUI, first exit the main app and any other instance using that key, then run:

```powershell
py -m offlook diagnose-search-shortcut
py -m offlook --config '<path>' diagnose-search-shortcut
```

Use the second form with your actual configuration path to test a custom key. The diagnostic prints the configured combination, reports registration and detection, and checks the selected local folder (or the current local folder when nothing is selected). It keeps listening after selection errors. It tests the saved search key even when **Enable global shortcuts** is off, without changing the file or switch; Ctrl+C stops it with exit code 0. An explicitly specified missing or invalid configuration reports an error and exits with code 2 rather than falling back to defaults.

### Compare two files

- In **File comparison**, click **Compare two files**. In the native Windows Open dialog, hold Ctrl and select exactly two files from the same folder, then click **Open**. OffLook assigns Old and New by path order, not click order; use **Swap files** to reverse them. **Cancel** closes the picker without comparing.
- In File Explorer or on the desktop, select exactly two local files and press **Ctrl+Alt+D**, the default **Compare files** shortcut. A folder or extra item in the selection prevents comparison. The shortcut assigns Old and New by path order, not click order. If OffLook is hidden to the tray, the comparison opens without restoring the main window.

Compare UTF-8 or Unicode text with a byte-order mark: TXT, Markdown, RST, CSV/TSV, logs, code, or even files without an extension. Markdown and HTML are compared as source text. OffLook can also compare body paragraphs and table text in Word `.docx` files, including against plain text; it does not compare Word layout, images, or headers and footers. DOCX line numbers refer to extracted text, not pages. Legacy `.doc`, PDFs, and other binary documents are not supported. The default limits are 2,000,000 bytes and 20,000 lines per file; larger inputs produce an error rather than a partial comparison. No Git installation, repository, or GitHub account is required.

The result opens in **Split** view (old on the left, new on the right). Switch to **Unified** to see both in one list. Red `-` lines are removals, green `+` lines are additions, and paired edits highlight the changed text within each line. A changed pair counts as one removal and one addition. OffLook shows nearby unchanged lines around each change; click **Show … unchanged lines** to reveal a collapsed section. A change to the final newline still counts as an edit to the last line; the `\ No newline at end of file` notice itself is not counted. Click **Swap files** to compare in the opposite direction. Esc or X closes the result without exiting OffLook.

## 4. Customize global shortcuts

Keep OffLook running, select one file in File Explorer or on the desktop, and press the **Preview** shortcut (default: **Ctrl+Space**). Pressing its shortcut again over that preview closes it. **Search files** (**Ctrl+Q**), **Compare files** (**Ctrl+Alt+D**), and **Convert files** (**Alt+C**) have separate configurable keys. These are defaults, not reserved keys.

In **Shortcut settings**, choose exactly one action: **Preview**, **Search files**, **Compare files**, or **Convert files**. Click **Record shortcut**, press a new combination inside OffLook, then click **Apply** to save only that action's key. Each action has its own draft, so switching away and back preserves completed edits without saving them. Esc cancels recording; switching actions also cancels unfinished recording and restores its prior draft. **Reset default** changes only the selected draft and also requires **Apply**. Recording an already-active key over the main window captures it without executing its feature.

**Enable global shortcuts** applies immediately to all four actions, independently of the selected-key Apply button. Disabling releases every global key without disabling manual preview, search, comparison, or conversion. Enabling attempts all four saved keys independently; an occupied key makes only that action **Unavailable**. Controls are temporarily disabled while registrations settle.

Shortcuts require Ctrl or Alt (or both), optionally Shift, and A–Z, 0–9, Space, or F1–F11. The Windows key, F12, and reserved combinations such as Alt+F4 and Alt+Space are not supported. All four saved combinations must be different, even while global shortcuts are disabled. A default key can be assigned to a different action after its previous owner is saved with a distinct key.

The cards and open Help window show actual active keys, or **Disabled**, **Registering**, or **Unavailable** with the configured key and reason. If registration or saving fails, the old active key remains and the proposed draft stays available for retry. Release an occupied key in the other application, then click Apply again, or choose a different combination. If external configuration changes request a swap of active keys, use an intermediate unused combination to release the old key; OffLook does not silently unregister both actions to swap them.

Settings are saved to `%LOCALAPPDATA%\OffLook\config.json` by default, or to the configuration file explicitly specified on the CLI. Older files missing shortcut fields use their defaults without being rewritten just by loading. A file with invalid or duplicate combinations is an explicit configuration error; correct the named fields rather than expecting a silent reset. The single-file `preview` CLI command does not register global shortcuts.

## 5. Background mode, startup, and Help

The main window's X button and **Hide to tray** hide OffLook only when the system tray is available. Double-click the OffLook icon in the notification area to restore it. Select **Exit** to close it completely.
Enable **Start when signing in to Windows** to launch in the background the next time the current user signs in; clear it to disable startup. Avoid running multiple background instances.

```powershell
py -m offlook --background
```

The **Help** button or F1 opens the offline guide with live status for all four shortcuts. Reopen Help after switching languages. If a shortcut does not respond, check its status and confirm that OffLook is running. For Preview or Compare files, bring File Explorer or the desktop to the foreground and select one file or exactly two local files, respectively. In File Explorer, Search files accepts one selected local folder or the current folder with nothing selected, and Convert files accepts one or more selected files. An input method may reserve a combination; change it or use the manual controls.

## 6. Convert, filter, and use AI

**Convert files**: select one or more files in File Explorer and press the default **Alt+C** shortcut, or click **Choose files to convert**. In the **Convert to** dropdown, choose a target shared by the selected files, then click **Convert** or press Enter. **Cancel**, Esc, or X dismisses the dialog. When all selected files are images and you choose PDF, they become pages of one PDF. Otherwise, files are converted individually. OffLook writes outputs next to the source and adds a number if an output name already exists.

Set **Quality** before opening the dialog. The formats and backends below determine which modes are useful. An offered target may still fail if its backend is missing. `python-docx` is installed with OffLook; `docx2pdf`, `openpyxl`, and `python-pptx` are optional packages.

| Source | Available outputs and requirements |
| --- | --- |
| Common images | PNG, JPEG, BMP, GIF, TIFF, WebP, ICO, or PDF. |
| PDF | PNG, JPEG, BMP, or TIFF. |
| Text, Markdown, code, and CSV | PDF, TXT, or Word (`.docx`). |
| Word (`.docx`) | TXT extracts paragraphs. For PDF, `auto` uses Microsoft Word and `docx2pdf` with no automatic fallback; `text` uses paragraphs only; `office` uses LibreOffice. |
| Excel (`.xlsx` / `.xlsm`) | CSV or TXT via `openpyxl`. PDF requires LibreOffice in `auto` or `office` mode. |
| PowerPoint (`.pptx` / `.pptm`) | In `text` mode, PDF, TXT, and DOCX use slide text via `python-pptx`. Layout-preserving PDF and PNG/JPEG require LibreOffice. For PDF, `auto` uses LibreOffice if available, otherwise it uses slide text. |
| Legacy Office (`.doc` / `.xls` / `.ppt`) | PDF via LibreOffice in `auto` or `office` mode. |
| HTML | TXT extracts readable text; PDF uses LibreOffice in `office` mode or when available in `auto`, and otherwise uses extracted text. |
| ZIP | **Extract archive** unpacks the ZIP to a new folder. |

**Filter files**: choose a folder, check any combination of categories, then click **Apply filter**. A file can match any checked category; leaving all boxes unchecked lists files without a type filter. The scan includes subfolders, skips symbolic links and inaccessible subfolders, and does not read file contents. Double-click a result to preview it. The [API](api.md#create-a-context-and-identify-files) also supports filename and extension filters. If combined, a result must match the filename and at least one value in each nonempty category or extension group.

**AI file assistant**: enter an OpenAI-compatible **Base URL** (for example, `https://api.deepseek.com`), a **Model** (for example, `deepseek-chat`), and your **API key**, then click **Save AI settings**. Saving does not contact the service. The key is saved in plaintext in the local JSON configuration; keep that file private. The **Enable AI assistant** checkbox is a saved preference, not a runtime access control.

To contact the service, enter an instruction such as `List PDF files in D:\Docs` and click **Run with AI**. Your instruction is sent to the configured service; subsequent requests may include tool results such as paths, filenames, and sizes. The assistant uses OffLook's local tools to list, filter, move, copy, or organize files. Use a service you trust, and start with a listing if you do not want to change files.

## Optional: manual PATH troubleshooting
If the UI is unavailable, run the same service from the project root:

```powershell
py -c "from offlook.platforms.windows_environment import add_offlook_to_user_path; print(add_offlook_to_user_path())"
```

This also changes only the user PATH. Reopen your terminal afterward. If policy prevents the change, an error is reported: do not elevate privileges or modify the system PATH. Continue using `py -m offlook` instead.
