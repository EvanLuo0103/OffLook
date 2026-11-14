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

## 4. Customize the shortcut

Keep OffLook running, select one file in File Explorer or on the desktop, and press the default Ctrl+Space shortcut to preview it.
Click **Record shortcut** in the main window, press a new combination, then click **Apply**. Esc cancels recording. **Reset default** also requires **Apply** to take effect.

Shortcuts require Ctrl or Alt (or both), optionally Shift, and A–Z, 0–9, Space, or F1–F11. The Windows key, F12, and reserved combinations such as Alt+F4 and Alt+Space are not supported. The old shortcut is kept if registration or saving fails.
Settings are saved to `%LOCALAPPDATA%\OffLook\config.json` by default, or to the configuration file explicitly specified on the CLI. Older files without a hotkey field use Ctrl+Space.

## 5. Background mode, startup, and Help

The main window's X button and **Hide to tray** do not exit OffLook. Double-click the OffLook icon in the notification area to restore it. Select **Exit** to close it completely.
Enable **Start when signing in to Windows** to launch in the background the next time the current user signs in; clear it to disable startup. Avoid running multiple background instances.

```powershell
py -m offlook --background
```

The **Help** button or F1 opens the offline guide. If the shortcut does not respond, check that OffLook is running, exactly one local file is selected, and File Explorer is in the foreground. An input method may reserve the combination; change the shortcut or select the file manually.

## Optional: manual PATH troubleshooting

If the UI is unavailable, run the same service from the project root:

```powershell
py -c "from offlook.platforms.windows_environment import add_offlook_to_user_path; print(add_offlook_to_user_path())"
```

This also changes only the user PATH. Reopen your terminal afterward. If policy prevents the change, an error is reported: do not elevate privileges or modify the system PATH. Continue using `py -m offlook` instead.
