"""Bilingual user-interface strings with a runtime switchable language.

Only presentation text lives here. Core modules keep raising English
``OffLookError`` messages; the GUI shows them verbatim because they describe file
system and configuration details that the user is expected to read literally.

Usage::

    from offlook.ui.i18n import tr, set_language, language
    label.configure(text=tr("btn.choose_file"))
    set_language("zh")
"""

from __future__ import annotations

LANGUAGES = ("en", "zh")
DEFAULT_LANGUAGE = "en"

# key: (English, Chinese).  Keeping both languages side by side in one table makes
# a missing translation a KeyError at import time instead of a silent English leak.
_TEXTS: dict[str, tuple[str, str]] = {
    # Application chrome
    "app.tagline": ("Local file previews", "本機檔案預覽"),
    "btn.help": ("Help", "說明"),
    "lang.english": ("English", "English"),
    "lang.chinese": ("中文", "中文"),
    "lang.tooltip": ("Interface language", "介面語言"),
    "page.tools": ("File tools", "檔案工具"),
    "page.settings": ("Settings", "設定"),

    # Cards
    "card.preview": ("Quick preview", "快速預覽"),
    "card.compare": ("File comparison", "檔案比對"),
    "card.convert": ("Convert files", "檔案轉換"),
    "card.search_filter": ("Search & filter", "搜尋與篩選"),
    "card.ai": ("AI file assistant", "AI 檔案助手"),
    "card.criteria": ("Criteria", "條件"),
    "card.ai_connection": ("Connection", "連線設定"),
    "card.ai_task": ("Instruction and response", "指令與回覆"),
    "card.shortcuts": ("Shortcut settings", "快捷鍵設定"),
    "card.integration": ("System integration", "系統整合"),

    # Preview card
    "btn.choose_file": ("Choose file", "選擇檔案"),

    # File comparison card and picker
    "btn.compare_files": ("Compare two files", "比對兩個檔案"),
    "status.diff.default": ("Choose two local text or Word (.docx) files to compare.",
                            "請選擇兩個本機文字檔或 Word（.docx）檔進行比對。"),
    "status.diff.choosing": ("Choose both files in the same window…", "請在同一個視窗內選取兩個檔案…"),
    "status.diff.cancelled": ("File comparison cancelled.", "已取消檔案比對。"),
    "status.diff.running": ("Comparing the two files…", "正在比對兩個檔案…"),
    "status.diff.ready": ("File comparison ready", "檔案比對完成"),
    "status.diff.differences": ("Differences found.", "發現差異。"),
    "status.diff.same": ("No differences between the files.", "兩個檔案沒有差異。"),
    "diff.old_file": ("Old file", "舊檔案"),
    "diff.new_file": ("New file", "新檔案"),
    "diff.swap": ("Swap files", "交換檔案"),

    # Convert card
    "btn.choose_convert": ("Choose files to convert", "選擇要轉換的檔案"),
    "hint.convert_shortcut": ("Select files in File Explorer and press the configured Convert files shortcut (default Alt+C).",
                              "在檔案總管選取檔案後按設定的轉換快捷鍵（預設 Alt+C）。"),
    "label.quality": ("Quality", "品質"),
    "hint.convert_mode": ("Quality depends on the file format · DOCX to PDF: auto uses Word, text uses paragraphs, office uses LibreOffice",
                          "品質視格式而定 · DOCX 轉 PDF：auto 用 Word、text 只取段落、office 用 LibreOffice"),
    "status.convert.default": ("Select files, then choose a target in the Convert to dialog.",
                               "先選擇檔案，再從「轉換格式」對話框選擇目標。"),
    "status.convert.none": ("No conversion is available for the selected files.",
                            "所選檔案沒有可用的轉換格式。"),
    "status.convert.running": ("Converting {n} file(s) to {target}…", "正在把 {n} 個檔案轉換為 {target}…"),
    "status.convert.done": ("Converted {n} file(s) → {m} output file(s).",
                            "已轉換 {n} 個檔案，產生 {m} 個輸出檔。"),
    "status.convert.failed": ("Conversion failed.", "轉換失敗。"),

    # Search card
    "btn.choose_folder": ("Choose folder", "選擇資料夾"),
    "btn.search": ("Search", "搜尋"),
    "label.search_name": ("File name", "檔名"),
    "label.search_types": ("File types (none = all)", "檔案類型（未勾選即不限）"),
    "col.type": ("Type", "類型"),
    "col.path": ("File", "檔案"),
    "status.search.default": ("Choose a folder to search recursively.", "選擇資料夾以遞迴搜尋。"),
    "status.search.ready": ("Ready to search.", "可以開始搜尋。"),
    "status.search.no_folder": ("Choose a folder first.", "請先選擇資料夾。"),
    "status.search.running": ("Searching…", "搜尋中…"),
    "status.search.found": ("{n} file(s) found.", "找到 {n} 個檔案。"),
    "status.search.explorer": ("Folder selected from File Explorer. Click Search when ready.",
                               "已從檔案總管選擇資料夾。準備好後按「搜尋」。"),
    "filter.dialog.close": ("Close", "關閉"),

    # AI card
    "check.ai_enable": ("Enable AI assistant", "啟用 AI 助手"),
    "field.base_url": ("Base URL", "服務位址"),
    "field.model": ("Model", "模型"),
    "field.api_key": ("API key", "API 金鑰"),
    "btn.save_ai": ("Save AI settings", "儲存 AI 設定"),
    "label.ai_instruction": ('Instruction (e.g. "move all PDF files in D:\\Docs to D:\\Archive")',
                             "指令（例如「把 D:\\Docs 內所有 PDF 移到 D:\\Archive」）"),
    "btn.run_ai": ("Run with AI", "用 AI 執行"),
    "hint.ai_run_privacy": ("Run sends your instruction and may send paths, names and sizes. Read-only unless you request and approve file changes.",
                            "執行會傳送指令，也可能傳送路徑、名稱和大小。預設唯讀，變更檔案須勾選審核並逐次批准。"),
    'check.ai_review_writes': ('Review file changes for this run', '審核本次執行的檔案變更'),
    'ai.approval': ('Review file changes', '審核檔案變更'),
    'ai.approve': ('Approve these changes', '批准這些變更'),
    'ai.deny': ('Deny', '拒絕'),
    'ai.source': ('Source', '來源'), 'ai.destination': ('Destination', '目的地'),
    'ai.directory': ('Create folder', '建立資料夾'), 'ai.skip': ('Skip', '略過'),
    'ai.op.move_files': ('Move files', '移動檔案'), 'ai.op.copy_files': ('Copy files', '複製檔案'),
    'ai.op.organize_by_kind': ('Move files into category folders', '移動檔案到分類資料夾'),
    'ai.remove_key': ('Remove saved key', '移除已儲存的金鑰'),
    'ai.key_saved': ('Key configured in Windows Credential Manager. Leave blank to keep it.', '已設定 Windows 認證管理員金鑰。留白可保留。'),
    'ai.legacy': ('The original configuration still contains a plaintext key. It will not be used until migration succeeds.', '原設定仍含明文金鑰。遷移成功前不會使用。'),
    'ai.key_missing': ('Saved API key not found; save it again.', '找不到已儲存的 API 金鑰；請重新儲存。'),
    'ai.change_endpoint': ('Enter a new key or remove the saved key before changing endpoints.', '變更服務位址前，請輸入新金鑰或移除已存金鑰。'),
    "hint.ai_quick": ("Save connection settings on the main AI page. Closing this window does not stop a run.",
                      "請在主視窗的 AI 頁面儲存連線設定。關閉此視窗不會中止執行。"),
    "status.ai.default": ("Connect your own AI (DeepSeek, OpenAI, or any compatible endpoint).",
                          "連接你自己的 AI（DeepSeek、OpenAI 或任何相容端點）。"),
    "status.ai.saved": ("AI settings saved", "AI 設定已儲存"),
    "status.ai.no_instruction": ("Enter an instruction first.", "請先輸入指令。"),
    "status.ai.no_key": ("Save an API key first.", "請先儲存 API 金鑰。"),
    "status.ai.running": ("Running assistant…", "助手執行中…"),
    "status.ai.finished": ("Assistant finished.", "助手已完成。"),
    "status.ai.tools": ("— Tool actions —", "— 工具動作 —"),

    # Shortcut card
    "check.enable_shortcuts": ("Enable global shortcuts", "啟用全域快捷鍵"),
    "action.preview": ("Preview", "預覽"),
    "action.search": ("Search & filter (main window)", "搜尋與篩選（主視窗）"),
    "action.diff": ("Compare files", "檔案比對"),
    "action.convert": ("Convert files", "檔案轉換"),
    "action.filter": ("Search & filter (quick window)", "搜尋與篩選（小視窗）"),
    "action.ai": ("AI file assistant", "AI 檔案助手"),
    "btn.record": ("Record shortcut", "錄製快捷鍵"),
    "btn.apply": ("Apply", "套用"),
    "btn.reset_default": ("Reset default", "還原預設"),
    "hint.shortcut_keys": ("Ctrl or Alt, with optional Shift; letters, digits, Space, F1–F11.",
                           "需含 Ctrl 或 Alt，可再加 Shift；可用字母、數字、Space、F1–F11。"),
    "hint.shortcut_switch": ("The shared switch applies immediately. Apply saves only the "
                             "selected action.",
                             "上方開關立即生效；「套用」只儲存目前選取的動作。"),
    "status.record.press": ("Press a key combination; Esc to cancel.", "請按下組合鍵，按 Esc 取消。"),
    "status.record.done": ("Recorded. Click Apply to save the selected shortcut.",
                           "已錄製，按「套用」儲存這個快捷鍵。"),
    "status.record.reserved": ("Windows-reserved shortcuts are not supported",
                               "不支援 Windows 保留的組合鍵"),
    "status.hotkey.saved_disabled": ("{label} shortcut saved. Global shortcuts are disabled.",
                                     "{label} 快捷鍵已儲存；全域快捷鍵目前停用。"),
    "status.hotkey.enabled": ("Global shortcuts enabled; see each action's availability.",
                              "已啟用全域快捷鍵，請看各動作的可用狀態。"),
    "status.hotkey.failed": ("{label}: {message}; shortcut settings were not applied.",
                             "{label}：{message}；快捷鍵設定未套用。"),
    "status.hotkey.active": ("{label} shortcut is active.", "{label} 快捷鍵已生效。"),
    "status.hotkey.applied": ("{label} shortcut applied.", "{label} 快捷鍵已套用。"),
    "status.hotkey.registering": ("Registering {combo}…", "正在註冊 {combo}…"),
    "status.hotkey.configured_inactive": ("configured {combo} is not active",
                                          "設定的 {combo} 尚未生效"),
    "status.hotkey.unavailable": ("Unavailable ({combo}): {reason}", "無法使用（{combo}）：{reason}"),
    "status.hotkey.not_registered": ("not registered", "未註冊"),
    "status.hotkey.attempted": ("attempted {combo}", "曾嘗試 {combo}"),
    "status.hotkey.disabled": ("Disabled", "已停用"),
    "status.hotkey.label": ("{label}: {message}", "{label}：{message}"),
    "status.hotkey.duplicate": ("Already active for {label}; use an unused combination first",
                                "此組合已被「{label}」使用；請先改用未被佔用的組合"),
    "status.selection.focus_changed": ("Foreground focus changed; selection cancelled.",
                                       "前景視窗已改變，已取消選取。"),
    "status.selection.no_files": ("No local files selected", "未選取任何本機檔案"),
    "status.selection.no_folder": ("No local folder selected.", "未選取任何本機資料夾。"),
    "status.selection.two_files": ("Select exactly two local files to compare.", "請選取兩個本機檔案進行比對。"),

    # Integration card
    "check.autostart": ("Start when signing in to Windows", "登入 Windows 時自動啟動"),
    "btn.add_path": ("Add to PATH", "加入 PATH"),
    "status.startup.on": ("Start at sign-in enabled", "已啟用登入時自動啟動"),
    "status.startup.off": ("Start at sign-in disabled", "已停用登入時自動啟動"),
    "status.path.updating": ("Updating user PATH…", "正在更新使用者 PATH…"),
    "status.path.added": ("Added to PATH: {dir}. Reopen PowerShell / Windows Terminal.",
                          "已加入 PATH：{dir}。請重開 PowerShell / Windows Terminal。"),
    "status.path.exists": ("Already in PATH: {dir}.", "PATH 中已存在：{dir}。"),
    "status.path.broadcast": (" Environment update notification failed.",
                              "（環境變數更新通知失敗。）"),
    "status.path.conflict": (" Another installation takes precedence: {exe}; run the command from the installation directory above.",
                             "（另一個版本優先：{exe}；請從上述安裝目錄執行命令。）"),

    # Footer and generic
    "btn.exit": ("Exit", "結束"),
    "btn.close": ("Close", "關閉"),
    "btn.hide": ("Hide to tray", "隱藏到系統匣"),
    "status.initial": ("Preview and file comparison run locally.", "預覽與檔案比對均在本機執行。"),
    "common.separator": ("; ", "；"),
    "status.tray_unavailable": ("System tray unavailable. Use Exit to close OffLook.",
                                "系統匣無法使用，請用「結束」關閉 OffLook。"),

    # File kinds
    "kind.all": ("All types", "所有類型"),
    "kind.text": ("Text", "文字"),
    "kind.markdown": ("Markdown", "Markdown"),
    "kind.code": ("Code", "程式碼"),
    "kind.csv": ("CSV", "CSV"),
    "kind.image": ("Images", "圖片"),
    "kind.pdf": ("PDF", "PDF"),
    "kind.document": ("Documents (.doc/.xlsx)", "文件（.doc/.xlsx）"),
    "kind.documents": ("Documents", "文件"),
    "kind.binary": ("Other / unknown", "其他／未知"),
    "kind.other": ("Other", "其他"),

    # Conversion dialog
    "convert.dialog.title": ("Convert to", "轉換格式"),
    "convert.dialog.convert": ("Convert", "轉換"),
    "convert.dialog.cancel": ("Cancel", "取消"),
    "convert.dialog.close": ("Close", "關閉"),
    "convert.dialog.unavailable": (" — Unavailable", " — 無法使用"),
    "convert.block.excel_pdf_mode": (
        "Excel to PDF is unavailable in Text mode; use Auto or Office mode (LibreOffice required).",
        "文字模式無法轉換 Excel 為 PDF；請切換至自動或 Office 模式（需要 LibreOffice）。"),
    "convert.block.slides_image_mode": (
        "Presentation images are unavailable in Text mode; use Auto or Office mode (LibreOffice required).",
        "文字模式無法將簡報轉換為圖片；請切換至自動或 Office 模式（需要 LibreOffice）。"),
    "convert.block.libreoffice": ("LibreOffice is required; install it or add soffice to PATH.",
                                 "需要 LibreOffice；請安裝或將 soffice 加入 PATH。"),
    "convert.block.openpyxl": ("Install the openpyxl Python package.", "請安裝 openpyxl Python 套件。"),
    "convert.block.pptx": ("Install the python-pptx Python package.", "請安裝 python-pptx Python 套件。"),
    "convert.block.docx2pdf": ("Install the docx2pdf Python package.", "請安裝 docx2pdf Python 套件。"),
    "convert.block.word": ("Microsoft Word is not registered; install Word, use Text mode, or use Office mode with LibreOffice.",
                           "找不到 Microsoft Word；請安裝 Word、使用文字模式，或使用搭配 LibreOffice 的 Office 模式。"),
    "convert.block.legacy_pdf_mode": ("Switch to Auto or Office mode (LibreOffice required).",
                                     "請切換至自動或 Office 模式（需要 LibreOffice）。"),
    "convert.block.slides_docx_mode": ("Switch to Auto or Text mode for Word output.",
                                      "請切換至自動或文字模式以輸出 Word。"),

    # Preview window
    "preview.info": ("Local file · Offline preview", "本機檔案 · 離線預覽"),
    "preview.always_on_top": ("Always on top", "置頂顯示"),
    "preview.loading": ("Loading…", "載入中…"),
    "preview.updating_resolution": ("Updating resolution…", "正在更新解析度…"),
    "preview.empty_file": ("Empty file", "空檔案"),
    "preview.close_status": ("Esc / Space to close", "按 Esc 或 Space 關閉"),
    "preview.close_hint": ("Esc / unmodified Space to close", "按 Esc 或 Space 關閉"),
    "preview.previous": ("Previous", "上一頁"),
    "preview.next": ("Next", "下一頁"),
    "preview.zoom_fit": ("Fit", "適應"),
    "preview.file_info": ("File information", "檔案資訊"),
    "preview.info_subtitle": ("Safe type icon · File contents not parsed",
                              "安全類型圖示 · 未解析檔案內容"),
    "preview.meta.name": ("File name", "檔案名稱"),
    "preview.meta.type": ("Type", "類型"),
    "preview.meta.path": ("Full path", "完整路徑"),
    "preview.meta.folder": ("Folder", "所在資料夾"),
    "preview.meta.size": ("Size", "大小"),
    "preview.meta.created": ("Created", "建立時間"),
    "preview.meta.modified": ("Modified", "修改時間"),
    "preview.meta.readonly": ("Read-only", "唯讀"),
    "preview.meta.hidden": ("Hidden", "隱藏"),
    "preview.meta.reason": ("Reason", "原因"),
    "preview.meta.unavailable": ("Unavailable", "無法取得"),
    "preview.meta.yes": ("Yes", "是"),
    "preview.meta.no": ("No", "否"),
    "preview.meta.no_extension": ("No extension", "無副檔名"),
    "preview.meta.default_reason": ("Content preview is not supported for this format",
                                    "此格式不支援內容預覽"),
    "preview.header_subtitle": ("{name} · {kind} · {size} bytes",
                                "{name} · {kind} · {size} 位元組"),

    # Help window
    "help.title": ("OffLook Help", "OffLook 說明"),
    "help.heading": ("Help", "說明"),
    "help.subtitle": ("Offline file previews and system integration", "離線檔案預覽與系統整合"),

    # Diff window
    "diff.title": ("File comparison — {name}", "檔案比對 — {name}"),
    "diff.heading": ("Comparison: {name}", "比對：{name}"),
    "diff.mode.split": ("Split", "並排"),
    "diff.mode.unified": ("Unified", "統一"),
    "diff.context.expand": ("Show {n} unchanged lines", "顯示 {n} 行未變更內容"),
    "diff.no_newline": ("\\ No newline at end of file", "\\ 檔案末尾沒有換行"),
    "diff.counts": ("{added} added · {deleted} deleted", "新增 {added} 行 · 刪除 {deleted} 行"),
    "diff.empty": ("No line differences.", "沒有行層級的差異。"),
}

_STRINGS: dict[str, dict[str, str]] = {
    "en": {key: pair[0] for key, pair in _TEXTS.items()},
    "zh": {key: pair[1] for key, pair in _TEXTS.items()},
}

_current = DEFAULT_LANGUAGE

# FileKind values are stable strings, so the display name can be resolved without
# importing the core package (which would couple the string table to file logic).
_KIND_KEYS = {
    "image": "kind.image", "pdf": "kind.pdf", "text": "kind.text",
    "markdown": "kind.markdown", "code": "kind.code", "csv": "kind.csv",
    "document": "kind.documents", "binary": "kind.other",
}


def kind_label(kind) -> str:
    """Return the translated display name for a FileKind or its string value."""
    value = getattr(kind, "value", kind)
    return tr(_KIND_KEYS.get(value, "kind.other"))


def language() -> str:
    """Return the active language code."""
    return _current


def set_language(code: str) -> str:
    """Switch the active language; ignore unknown values and return the active one."""
    global _current
    if isinstance(code, str) and code in LANGUAGES:
        _current = code
    return _current


def normalize_language(code: object) -> str:
    """Return a supported language code, falling back to the default."""
    return code if isinstance(code, str) and code in LANGUAGES else DEFAULT_LANGUAGE


def tr(key: str, **values: object) -> str:
    """Return the active-language text for ``key``.

    Unknown keys return the key itself so a missing translation is visible during
    testing instead of raising inside a Tk callback.
    """
    return tr_in(_current, key, **values)


def tr_in(language_code: str, key: str, **values: object) -> str:
    """Return ``key`` rendered in a specific language, ignoring the active one."""
    table = _STRINGS.get(language_code) or _STRINGS[DEFAULT_LANGUAGE]
    text = table.get(key)
    if text is None:
        text = _STRINGS[DEFAULT_LANGUAGE].get(key, key)
    if not values:
        return text
    try:
        return text.format(**values)
    except (KeyError, IndexError, ValueError):
        return text


def keys() -> tuple[str, ...]:
    """Return every known key, used by the translation completeness test."""
    return tuple(_TEXTS)


def missing(language_code: str) -> tuple[str, ...]:
    """Return keys without a translation for ``language_code``."""
    table = _STRINGS.get(language_code, {})
    english = _STRINGS[DEFAULT_LANGUAGE]
    return tuple(key for key in english if not table.get(key))


__all__ = [
    "DEFAULT_LANGUAGE",
    "LANGUAGES",
    "kind_label",
    "keys",
    "language",
    "missing",
    "normalize_language",
    "set_language",
    "tr",
    "tr_in",
]
