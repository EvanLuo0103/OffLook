# OffLook

OffLook is a Windows app and command-line tool for previewing, finding, comparing, and converting local files. With OffLook running in the system tray, select a file in File Explorer, press **Ctrl+Space** to preview it, and press **Esc** to close the preview.

- Preview PDFs, images, Markdown, text, code, and CSV.
- Find files recursively by name and file type.
- Compare text and Word (`.docx`) files side by side without Microsoft Word.
- Convert Markdown to PDF or combine several images into one PDF.

Preview, search, and comparison run locally. The optional AI assistant contacts the service you configure only when you run an AI task; its file tools are read-only by default.

## Install on Windows

Use 64-bit Python 3.11 to 3.15 with Tcl/Tk and the Python Launcher:

```powershell
py -m pip install --user offlook
py -m offlook
```

To install optional Python libraries for Office conversion, use `py -m pip install --user "offlook[office]"`. Some conversions also require a separate installation of Microsoft Word or LibreOffice.

## Use from PowerShell

```powershell
ol --help
ol filter . --kind pdf --name report
ol compare before.txt after.docx
ol convert scan1.png scan2.png --to pdf
```

If `ol` is not on PATH, use `py -m offlook` in its place. Run `py -m offlook path add` to add the command to your user PATH, then reopen the terminal.

See the [user guide](https://github.com/EvanLuo0103/OffLook/blob/main/docs/getting-started.md) for setup, shortcuts, supported formats, and CLI exit codes. The source distribution also includes the user guide and both language versions of the README.
