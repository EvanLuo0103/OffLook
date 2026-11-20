"""Built-in help window in the active language; no browser or external reader."""
from __future__ import annotations

from collections.abc import Mapping
import tkinter as tk
from tkinter import ttk

from offlook.ui.i18n import language, tr
from offlook.ui.theme import COLORS, window_fonts, size_window


_HELP_EN = """Choosing a file to preview
Click "Choose file" in "File tools", or run:
  py -m offlook preview ".\\README.md"
Select one file in File Explorer or on the desktop, then press the configured Preview shortcut. Its default is Ctrl+Space.

Search & filter
Choose a local folder, optionally enter part of a filename, and check any number of file types. A file must match the name and any checked type. No checked types means all types. Click "Search" or press Enter in the filename field. Subfolders are included without following links or network folders. Double-click a result or select it and press Enter to preview.
In File Explorer, select one local folder or leave the selection empty in a local folder. Ctrl+Alt+F opens only the quick window and does not start a scan. A selected file or multiple items is an error, not a request to use the parent folder.
Run `py -m offlook filter [FOLDER]` for paths or add `--gui` for the quick window. The folder defaults to the terminal's current folder and is fixed in the quick window. `--kind` preselects types; enter the filename in the window. `--gui` cannot be combined with `--name` or `--ext`.

File comparison
In the "File comparison" card, click "Compare two files". In the Windows Open dialog, hold Ctrl and select exactly two files from the same folder, then click Open. You can also select two local files in File Explorer or on the desktop and press Compare files (default: Ctrl+Alt+D). Both methods sort the paths to set the initial order; Swap files reverses it. No Git installation or repository is needed.
Compare plain text (such as TXT, Markdown, RST, CSV or code) and Word (.docx) body paragraphs and tables, even across formats. Each file is limited to 2,000,000 bytes and 20,000 lines; Word layout is not compared. Split and Unified show green + additions, red - deletions, and stronger highlighting within edited lines. DOCX preview still shows metadata only.

Converting files
Select files in File Explorer and press the configured Convert files shortcut (default Alt+C), or click "Choose files to convert" in "File tools". The shortcut opens only the conversion dialog. Choose a target and click Convert or press Enter. Before starting, Cancel, Esc or X dismisses the chooser. Progress, output paths and errors stay in the same window; click Close when done. For DOCX to PDF, auto uses Microsoft Word with optional docx2pdf, text uses paragraph text, and office uses LibreOffice.

Command line
Run `ol --help` for all commands, including search, compare, convert, copy, move, organize, settings, startup and path. To see a command's options, add `--help` after its name. Use Settings → Add to PATH if `ol` is not found.

AI file assistant
Save an OpenAI-compatible endpoint, model and API key on the main AI page. The key goes into Windows Credential Manager. Ctrl+Alt+Shift+A opens only the AI quick window. Run sends your instruction and may send local paths, names and sizes. Tools are read-only by default. To request a write, check “Review file changes for this run” and approve each plan. Closing the originating view denies pending writes; it does not roll back an approved operation.

Switching the interface language
Use the "中文 / English" buttons at the top-right of the main window. Switching languages saves the choice and closes this Help window; reopen Help to view it in the selected language.

Current global shortcuts
Preview: {preview}
Compare files: {diff}
Convert files: {convert}
Search & filter (quick window): {filter}
AI file assistant: {ai}
This summary updates when shortcut registration changes. An active key can differ from the configured key if a replacement fails.
Esc or unmodified Space closes the preview; Space with Ctrl, Alt, or Shift does not.
All features remain available from the main window when shortcuts are disabled or unavailable.

Preview controls
PDFs have Previous / Next buttons; page numbers appear only for rendered PDF pages. "Always on top" applies only to the current preview.
The mouse wheel scrolls the main and preview windows over most controls. Dropdowns such as Quality keep their native wheel behavior, and result lists and text boxes scroll themselves while content remains.
When the preview needs a larger physical-pixel viewport, OffLook renders images and PDFs again within the raster limits. Moving to a higher-DPI display alone does not guarantee a larger render.

Shortcut settings and conflicts
Select an action under Shortcut settings. Each action keeps its own draft. Click "Record shortcut", press a combination inside OffLook, then click "Apply" to save only the selected action. Esc cancels recording; switching actions cancels unfinished recording. "Reset default" changes only the selected draft and also requires Apply.
"Enable global shortcuts" applies immediately to all actions, independently of Apply. Disabling releases all keys; enabling attempts each saved key independently. A key that another application owns is shown as Unavailable, while the other actions can still work.
Combinations must be different for all actions, even while disabled. If registration or saving fails, the previous active key remains and the draft is kept. Free the occupied key before retrying. Editing JSON does not live-reload shortcuts; restart OffLook to load changes. Swapping two live bindings requires an unused intermediate key.
Recording captures the combination without activating its feature, even for an already registered key.
Win-key combinations, F12, single keys, and reserved combinations such as Alt+F4 are not supported. Choose a combination with Ctrl or Alt, optionally Shift.

Add to or remove from PATH
Settings → System integration updates only the current user's PATH. Remove from PATH only removes an entry OffLook recorded adding for this installation. Reopen PowerShell afterward; restart Windows Terminal if needed.

System tray, startup, and exit
Closing the main window hides it only when the system tray is available. Restore it from the tray or choose Exit to stop background listening. Start at sign-in must be explicitly enabled.

File limits and offline operation
Preview and file comparison do not contact the network or execute file contents. They do not use third-party thumbnail providers.
Oversized images and PDFs show metadata instead of decoded content. Long text may be truncated, and empty text shows an Empty file notice. Fit does not enlarge small source images automatically; manual zoom is separate.
Content previews support images, PDFs, text, Markdown, code, and CSV. Word, Excel, PowerPoint, OpenDocument, unknown, and unsupported files show the information card with the full path, file attributes, and human-readable size.
"""

_HELP_ZH = """選擇要預覽的檔案
在「檔案工具」按「選擇檔案」，或執行：
  py -m offlook preview ".\\README.md"
在檔案總管或桌面選取一個檔案，然後按已設定的「預覽」快捷鍵（預設 Ctrl+Space）。

搜尋與篩選
選擇本機資料夾，可選填部分檔名及勾選多個類型。檔案必須符合檔名和任一勾選的類型；未勾選即不限類型。按「搜尋」或在檔名欄按 Enter 開始。搜尋包含子資料夾，但不跟隨連結或網路資料夾。雙擊結果或選取結果後按 Enter 即可預覽。
在檔案總管選取一個本機資料夾，或在本機資料夾內不選取任何項目。Ctrl+Alt+F 只開啟小視窗，不會自動掃描。選取一般檔案或多個項目是錯誤，不會改用上層資料夾。
執行 `py -m offlook filter [FOLDER]` 可輸出路徑；加 `--gui` 則開啟小視窗。省略 FOLDER 時使用終端機的目前目錄。小視窗目錄固定，`--kind` 可預選類型，檔名可在視窗輸入；`--gui` 不可與 `--name` 或 `--ext` 一起使用。

檔案比對
在「檔案比對」卡片按「比對兩個檔案」，在 Windows 開啟檔案對話框按住 Ctrl，從同一資料夾選取正好兩個檔案，再按「開啟」。也可在檔案總管或桌面選取正好兩個本機檔案，再按檔案比對快捷鍵（預設 Ctrl+Alt+D）。兩種方式都依路徑排序，可用「交換檔案」反轉方向。不需要 Git 或儲存庫。
支援 TXT、Markdown、RST、CSV、程式碼等純文字，以及 Word（.docx）正文段落和表格，可跨格式比對。每份檔案上限 2,000,000 位元組和 20,000 行；不比較 Word 版面。「並排」和「統一」視圖以綠色 + 標示新增、紅色 - 標示刪除，並加深顯示行內改動。DOCX 預覽仍僅顯示中繼資料。

轉換檔案
在檔案總管選取檔案並按轉換快捷鍵（預設 Alt+C），或在「檔案工具」按「選擇要轉換的檔案」。快捷鍵只開啟轉換小視窗。選擇格式後按「轉換」或 Enter；開始前可按「取消」、Esc 或 X。進度、輸出路徑和錯誤都在同一個視窗顯示，完成後按「關閉」。DOCX 轉 PDF 時，auto 使用 Microsoft Word 與選用的 docx2pdf，text 只取段落文字，office 使用 LibreOffice。

命令列
執行 `ol --help` 查看所有命令，包括 search、compare、convert、copy、move、organize、settings、startup 和 path。在命令名稱後加 `--help` 可查看參數；找不到 `ol` 時，請在設定中加入 PATH。

AI 檔案助手
在主視窗的 AI 頁面儲存 OpenAI 相容端點、模型及 API 金鑰。金鑰存放於 Windows 認證管理員。Ctrl+Alt+Shift+A 只開啟 AI 小視窗。執行會傳送指令，並可能傳送本機路徑、名稱及大小。工具預設唯讀；若需變更檔案，請勾選「審核本次執行的檔案變更」，並逐次批准。關閉發出指令的視窗會拒絕待審核變更，但不會復原已批准的作業。

切換介面語言
使用右上方的「中文 / English」按鈕。切換語言會儲存選擇並關閉說明視窗；重新開啟即可閱讀新語言的說明。

目前的通用快捷鍵
預覽：{preview}
檔案比對：{diff}
檔案轉換：{convert}
搜尋與篩選（小視窗）：{filter}
AI 檔案助手：{ai}
這份摘要會在快捷鍵註冊狀態變更時更新。若替換失敗，實際生效的按鍵可能與設定的不同。
按 Esc 或單獨的 Space 會關閉預覽；Space 加上 Ctrl、Alt 或 Shift 則不會。
即使全域快捷鍵停用或無法使用，仍可從主視窗手動使用所有功能。

預覽操作
PDF 有「上一頁」「下一頁」按鈕；頁碼只在有實際繪製的 PDF 頁面顯示。「置頂顯示」只作用於目前這個預覽視窗。
主視窗與預覽視窗大多數控制項上都可用滾輪捲動；「品質」等下拉選單保留原生滾輪行為，結果清單與文字框則優先捲動自己的內容。
預覽區需要更多實際像素時，OffLook 會在點陣圖上限內重新繪製圖片或 PDF；單純切換 DPI 不一定會提高繪製解析度。

快捷鍵設定與衝突
在快捷鍵設定選擇一項動作。每個動作各自保留草稿。按「錄製快捷鍵」，在 OffLook 視窗內按下組合鍵，再按「套用」只儲存目前選取的動作。按 Esc 取消錄製；切換動作也會取消未完成的錄製。「還原預設」只會改動目前草稿，同樣需要按「套用」。
「啟用全域快捷鍵」會立即套用到所有動作，與「套用」無關。停用會釋放所有按鍵；啟用會逐一嘗試各動作已儲存的按鍵。被其他程式佔用的按鍵會顯示為「無法使用」，其他動作仍可正常運作。
所有動作的組合必須互不相同，即使在全域快捷鍵停用時也一樣。註冊或儲存失敗會保留原本生效的按鍵和草稿。請釋放已佔用的按鍵後再試。編輯 JSON 不會即時載入快捷鍵；請重啟 OffLook。交換兩個已生效的快捷鍵需要先使用一個未被佔用的組合。
即使按下已註冊的快捷鍵，錄製時也只會捕捉按鍵，不執行功能。
不支援 Win 鍵組合、F12、單一按鍵，以及 Alt+F4 這類保留組合。請選擇含 Ctrl 或 Alt（可再加 Shift）的組合。

加入或從 PATH 移除
「設定 → 系統整合」只修改目前使用者的 PATH。「從 PATH 移除」只會移除 OffLook 為此安裝加入且有記錄的項目。之後請重開 PowerShell；必要時也重開 Windows Terminal。

系統匣、開機啟動與結束
系統匣可用時，關閉主視窗會隱藏至系統匣，可從該處還原或選擇結束。登入時自動啟動須明確啟用。結束程式會停止背景監聽。

檔案上限與離線運作
預覽和檔案比對不會連線，也不會執行檔案內容或使用外部縮圖處理程式。
超過預覽限制的圖片與 PDF 只顯示中繼資料，文字過長可能截斷，空白文字檔會顯示空檔案提示。「適應」不會自動放大小圖；手動縮放另計。
可預覽的內容包括圖片、PDF、文字、Markdown、程式碼與 CSV。Word、Excel、PowerPoint、OpenDocument、未知與不支援的格式會顯示資訊卡，包含完整路徑、檔案屬性與易讀的大小。
"""


def _help_body(shortcuts: Mapping[str, str]) -> str:
    """Render the language-appropriate help text with the live shortcut summary."""
    template = _HELP_ZH if language() == "zh" else _HELP_EN
    return template.format(
        preview=shortcuts["preview"],
        diff=shortcuts["diff"],
        convert=shortcuts["convert"],
        filter=shortcuts["filter"],
        ai=shortcuts.get("ai", tr("status.hotkey.not_registered")),
    )


def show_help(parent: tk.Misc, *, shortcuts: Mapping[str, str]) -> tk.Toplevel:
    """Create and return one scrollable, read-only help Toplevel."""
    window = tk.Toplevel(parent)
    window._offlook_font_prefix = "Help"
    window.title(tr("help.title"))
    window.transient(parent)
    try:
        dpi = 96
        from offlook.platforms.windows_dpi import window_dpi
        dpi = window_dpi(window.winfo_id())
    except (ImportError, OSError, tk.TclError):
        dpi = 96
    fonts = window_fonts(window, dpi)
    size_window(window, dpi, 720, 680, 500, 380, monitor=parent)
    window.configure(background=COLORS["background"])
    header = ttk.Frame(window, style="Card.TFrame", padding=(24, 18, 24, 10))
    header.pack(fill="x", padx=16, pady=(16, 0))
    ttk.Label(header, text=tr("help.heading"), style="Help.Title.TLabel").pack(anchor="w")
    ttk.Label(header, text=tr("help.subtitle"), style="Card.Muted.TLabel").pack(anchor="w", pady=(4, 0))
    frame = ttk.Frame(window, style="Card.TFrame", padding=(24, 12, 12, 16))
    frame.pack(fill="both", expand=True, padx=16, pady=(0, 16))
    text = tk.Text(frame, wrap="word", relief="flat", borderwidth=0,
                   background=COLORS["card"], foreground=COLORS["text"],
                   insertbackground=COLORS["text"], padx=4, pady=4,
                   font=fonts["body"], spacing1=2, spacing3=6)
    scroll = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
    text.configure(yscrollcommand=scroll.set)
    text.grid(row=0, column=0, sticky="nsew")
    scroll.grid(row=0, column=1, sticky="ns")
    frame.rowconfigure(0, weight=1)
    frame.columnconfigure(0, weight=1)
    window._offlook_help_text = text
    text.configure(cursor="arrow")
    update_help_shortcuts(window, shortcuts=shortcuts)
    window.bind("<Escape>", lambda _event: window.destroy())
    window.protocol("WM_DELETE_WINDOW", window.destroy)
    window.focus_set()
    return window


def update_help_shortcuts(window: tk.Toplevel, *, shortcuts: Mapping[str, str]) -> None:
    """Refresh the existing Help body without changing focus or scroll position."""
    text = window._offlook_help_text
    position = text.yview()[0]
    content = _help_body(shortcuts)
    text.configure(state="normal")
    text.delete("1.0", "end")
    text.insert("1.0", content)
    text.configure(state="disabled")
    text.yview_moveto(position)
