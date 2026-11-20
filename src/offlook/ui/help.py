"""Built-in help window in the active language; no browser or external reader."""
from __future__ import annotations

from collections.abc import Mapping
import tkinter as tk
from tkinter import ttk

from offlook.ui.i18n import language, tr
from offlook.ui.theme import COLORS, window_fonts, size_window


_HELP_EN = """Choosing a file to preview
Click "Choose file" in the main window, or run:
  offlook preview ".\\README.md"
Select one file in File Explorer or on the desktop, then press the configured Preview shortcut. Its default is Ctrl+Space.

Searching files
In "Search files", choose a local folder and optionally enter part of a filename. Choose "All types", a content category, "Documents (.doc/.xlsx)", or "Other / unknown", then click "Search".
The search includes subfolders but does not follow links or network folders. Double-click a result to preview it.
In File Explorer, select one local folder, or open a local folder with nothing selected, then press the configured Search files shortcut (default: Ctrl+Q). OffLook loads the folder and focuses the filename field; it does not run a search until you click "Search". A selected regular file or multiple items is an error, not a request to search the parent folder.

File comparison
The separate "File comparison" card contains "Compare two files". Choose the first and second UTF-8 text files, or select exactly two local files in File Explorer and press the configured Compare files shortcut (default: Ctrl+Alt+D). The window compares the files line by line and highlights added green, deleted red, and modified amber lines.
Office and OpenDocument files are identified for searching, but OffLook shows their metadata instead of parsing their contents.

Converting files
Select one or more files in File Explorer and press the convert shortcut (default Alt+C) to open a format wheel, then choose a target format to convert locally. You can also click "Choose files to convert" in the main window. Images convert between PNG, JPEG, BMP, GIF, TIFF, WebP, and ICO, and to PDF; PDFs convert to image formats; text, Markdown, code, and CSV convert to PDF, TXT, or Word. Word, Excel, and PowerPoint convert to PDF/TXT/CSV/images using the optional python-docx, openpyxl, and python-pptx packages. The Quality selector chooses fidelity: auto keeps images/layout when LibreOffice is installed, text is text-only, and office requires LibreOffice.

Filtering files
In "Filter files", choose a local folder and check any combination of formats, then click "Apply filter" to list matching files recursively. Double-click a result to preview it.

AI file assistant
The "AI file assistant" card is an opt-in port: enter your own OpenAI-compatible endpoint (for example DeepSeek's base URL), model, and API key, then describe a file task in plain language. The assistant may call OffLook's local list, filter, move, copy, and organize tools to act on your files. No network request is made unless you run the assistant with an API key.

Switching the interface language
Use the "中文 / English" buttons at the top-right of the main window. The choice is saved to the local configuration file and applied immediately, including to this Help window the next time it opens.

Current global shortcuts
Preview: {preview}
Search files: {search}
Compare files: {diff}
Convert files: {convert}
This summary updates when shortcut registration changes. An active key can differ from the configured key if a replacement fails.
Esc or unmodified Space closes the preview; Space with Ctrl, Alt, or Shift does not.
You can still choose files, search, and compare manually when global shortcuts are disabled or unavailable.

Preview controls
PDFs have Previous / Next buttons; page numbers appear only for rendered PDF pages. "Always on top" applies only to the current preview.
The mouse wheel scrolls the main window and each preview window from anywhere inside them, including over buttons, labels, the file path field, and the Quality selector. Result lists, text boxes, and tables keep their own scrolling while they still have hidden content, and otherwise the page keeps scrolling. The scrollbar on the right still works.
When you enlarge the window or move it to a higher-DPI display, images and PDFs are rendered again with more physical pixels, rather than repeatedly enlarging the old image.

Shortcut settings and conflicts
Choose Preview, Search files, Compare files, or Convert files in the action selector. Each action keeps its own draft. Click "Record shortcut", press a combination inside OffLook, then click "Apply" to save only the selected action. Esc cancels recording; switching actions cancels unfinished recording. "Reset default" changes only the selected draft and also requires Apply.
"Enable global shortcuts" applies immediately to all four actions, independently of Apply. Disabling releases all keys; enabling attempts each saved key independently. A key that another application owns is shown as Unavailable, while the other actions can still work.
Combinations must be different for all four actions, even while disabled. If registration or saving fails, the previous active key remains; the proposed draft is kept for correction or retry. Release an occupied key in the other application, then Apply again, or choose another combination. Changing externally configured keys does not implicitly swap active registrations: use an intermediate unused key to release the old one.
Recording does not activate a shortcut or execute a feature, including when you press an already-registered Search files or Compare files key over OffLook's main window.
Win-key combinations, F12, single keys, and reserved combinations such as Alt+F4 are not supported. Choose a combination with Ctrl or Alt, optionally Shift.

Add to PATH
"Add to PATH" in the main window updates only the current user's environment. It does not change the system PATH or other versions. Reopen PowerShell afterward; restart Windows Terminal if needed.
Existing terminals may still use the old environment. You can also run `py -m offlook`.

System tray, startup, and exit
Closing the main window hides it to the system tray, where you can restore it or exit. Start at sign-in must be explicitly enabled in the main window. Exiting stops background listening and pending work.

File limits and offline operation
OffLook reads only local files. It makes no network connections, executes no file content, and uses no Windows or third-party thumbnail providers.
Safety limits apply to file size, text length, image pixels, and preview time. Unknown formats, files over these limits, and empty files show a file information card, not a hex dump.
Content previews support images, PDFs, text, Markdown, code, and CSV. Word, Excel, PowerPoint, OpenDocument, unknown, and unsupported files show the information card with the full path, file attributes, and human-readable size.
"""

_HELP_ZH = """選擇要預覽的檔案
在主視窗按「選擇檔案」，或執行：
  offlook preview ".\\README.md"
在檔案總管或桌面選取一個檔案，然後按已設定的「預覽」快捷鍵（預設 Ctrl+Space）。

搜尋檔案
在「檔案搜尋」中選擇本機資料夾，可選擇性輸入檔名的一部分，再選擇「所有類型」、某個內容類型、「文件（.doc/.xlsx）」或「其他／未知」，然後按「搜尋」。
搜尋會包含子資料夾，但不會跟隨連結或網路資料夾。在結果上雙擊即可預覽。
在檔案總管中選取一個本機資料夾（或開啟資料夾且未選取任何項目），再按「檔案搜尋」快捷鍵（預設 Ctrl+Q）。OffLook 會載入該資料夾並把游標放到檔名欄，在你按「搜尋」之前不會真的開始搜尋。若選取的是單一檔案或多個項目，會視為錯誤，不會改成搜尋上層資料夾。

檔案比對
「檔案比對」卡片內有「比對兩個檔案」。可依序選擇兩個 UTF-8 文字檔，或在檔案總管選取兩個本機檔案後按「檔案比對」快捷鍵（預設 Ctrl+Alt+D）。比對視窗會逐行顯示差異，並以綠色標示新增、紅色標示刪除、琥珀色標示修改。
Office 與 OpenDocument 檔案會被辨識（供搜尋分類用），但 OffLook 只顯示中介資料，不會解析內容。

轉換檔案
在檔案總管選取一或多個檔案，按轉換快捷鍵（預設 Alt+C）開啟格式輪，選擇目標格式即可在本機轉換。也可以在主視窗按「選擇要轉換的檔案」。圖片可在 PNG、JPEG、BMP、GIF、TIFF、WebP、ICO 之間互轉，並可轉為 PDF；PDF 可轉為圖片；文字、Markdown、程式碼、CSV 可轉為 PDF、TXT 或 Word。Word、Excel、PowerPoint 透過選用的 python-docx、openpyxl、python-pptx 轉為 PDF／TXT／CSV／圖片。「品質」選項決定保真度：auto 在已安裝 LibreOffice 時保留圖片與版面，text 只取文字，office 則必須有 LibreOffice。

篩選檔案
在「檔案篩選」中選擇本機資料夾，勾選任意格式組合，按「套用篩選」就會遞迴列出符合的檔案。在結果上雙擊即可預覽。

AI 檔案助手
「AI 檔案助手」卡片是選用功能：填入你自己的 OpenAI 相容端點（例如 DeepSeek 的服務位址）、模型與 API 金鑰，然後用自然語言描述要處理的檔案工作。助手可能會呼叫 OffLook 本機的清單、篩選、移動、複製、分類工具來處理你的檔案。除非你填入 API 金鑰並執行助手，否則不會有任何網路請求。

切換介面語言
使用主視窗右上角的「中文 / English」按鈕。選擇會存到本機設定檔並立即生效；下次開啟本說明視窗時也會使用該語言。

目前的通用快捷鍵
預覽：{preview}
檔案搜尋：{search}
Git 比對：{diff}
檔案轉換：{convert}
這份摘要會在快捷鍵註冊狀態變更時更新。若替換失敗，實際生效的按鍵可能與設定的不同。
按 Esc 或單獨的 Space 會關閉預覽；Space 加上 Ctrl、Alt 或 Shift 則不會。
即使通用快捷鍵停用或不可用，你仍可手動選擇檔案、搜尋與比對。

預覽操作
PDF 有「上一頁」「下一頁」按鈕；頁碼只在有實際繪製的 PDF 頁面顯示。「置頂顯示」只作用於目前這個預覽視窗。
滑鼠滾輪可以在主視窗與各預覽視窗內的任何位置捲動，包括按鈕、標籤、檔案路徑欄與「品質」選單上方。結果清單、文字框與表格仍有隱藏內容時會優先捲動自己，捲到底之後才改為捲動頁面。右側的滾軸一樣可用。
放大視窗或把視窗移到更高 DPI 的螢幕時，圖片與 PDF 會用更多實際像素重新繪製，而不是把舊圖放大。

快捷鍵設定與衝突
在動作選單選擇「預覽」「檔案搜尋」「Git 比對」或「檔案轉換」。每個動作各自保留草稿。按「錄製快捷鍵」，在 OffLook 視窗內按下組合鍵，再按「套用」只儲存目前選取的動作。按 Esc 取消錄製；切換動作也會取消未完成的錄製。「還原預設」只會改動目前草稿，同樣需要按「套用」。
「啟用全域快捷鍵」會立即套用到全部四個動作，與「套用」無關。停用會釋放所有按鍵；啟用會逐一嘗試各動作已儲存的按鍵。被其他程式佔用的按鍵會顯示為「無法使用」，其他動作仍可正常運作。
四個動作的組合必須互不相同，即使在全域快捷鍵停用時也一樣。若註冊或儲存失敗，原本生效的按鍵會保留，草稿也會留著讓你修正或重試。請先在另一個程式釋放該按鍵再按「套用」，或改用其他組合。從外部變更設定檔的按鍵不會自動交換已註冊的按鍵：請先用一個未被佔用的組合釋放舊鍵。
錄製過程不會啟用快捷鍵，也不會執行任何功能；即使你在 OffLook 主視窗上按下已註冊的「檔案搜尋」或「Git 比對」鍵也一樣。
不支援 Win 鍵組合、F12、單一按鍵，以及 Alt+F4 這類保留組合。請選擇含 Ctrl 或 Alt（可再加 Shift）的組合。

加入 PATH
主視窗的「加入 PATH」只會修改目前使用者的環境變數，不會改動系統 PATH 或其他版本。之後請重開 PowerShell；必要時也重開 Windows Terminal。
已開啟的終端機可能仍在用舊的環境變數。你也可以直接執行 `py -m offlook`。

系統匣、開機啟動與結束
關閉主視窗只是隱藏到系統匣，可從系統匣還原或結束。登入時自動啟動必須在主視窗明確啟用。結束程式會停止背景監聽與未完成的工作。

檔案上限與離線運作
OffLook 只讀取本機檔案，不建立網路連線、不執行檔案內容，也不使用 Windows 或第三方的縮圖處理程式。
檔案大小、文字長度、圖片像素與預覽時間都有安全上限。未知格式、超過上限的檔案與空檔案會顯示檔案資訊卡，而不是十六進位內容。
可預覽的內容包括圖片、PDF、文字、Markdown、程式碼與 CSV。Word、Excel、PowerPoint、OpenDocument、未知與不支援的格式會顯示資訊卡，包含完整路徑、檔案屬性與易讀的大小。
"""


def _help_body(shortcuts: Mapping[str, str]) -> str:
    """Render the language-appropriate help text with the live shortcut summary."""
    template = _HELP_ZH if language() == "zh" else _HELP_EN
    return template.format(
        preview=shortcuts["preview"],
        search=shortcuts["search"],
        diff=shortcuts["diff"],
        convert=shortcuts["convert"],
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
