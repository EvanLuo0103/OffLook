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
    "app.tagline": ("Lightweight previews · Fully offline", "輕巧預覽 · 全程離線"),
    "btn.help": ("Help", "說明"),
    "lang.english": ("English", "English"),
    "lang.chinese": ("中文", "中文"),
    "lang.tooltip": ("Interface language", "介面語言"),

    # Cards
    "card.preview": ("Quick preview", "快速預覽"),
    "card.git": ("Git comparison", "Git 比對"),
    "card.convert": ("Convert files", "檔案轉換"),
    "card.search": ("Search files", "檔案搜尋"),
    "card.filter": ("Filter files", "檔案篩選"),
    "card.ai": ("AI file assistant", "AI 檔案助手"),
    "card.shortcuts": ("Shortcut settings", "快捷鍵設定"),
    "card.integration": ("System integration", "系統整合"),

    # Preview card
    "btn.choose_file": ("Choose file", "選擇檔案"),

    # Git card
    "btn.compare_head": ("Compare with Git HEAD", "與 Git HEAD 比對"),
    "status.diff.default": ("Select a tracked text file to compare with Git HEAD.",
                            "選擇一個受 Git 追蹤的文字檔，與 HEAD 版本比對。"),
    "status.diff.choosing": ("Choose a file in the file picker…", "請在檔案選擇視窗挑選檔案…"),
    "status.diff.selected": ("Selected: {name}. Comparing…", "已選擇 {name}，比對中…"),
    "status.diff.cancelled": ("Git comparison cancelled.", "已取消 Git 比對。"),
    "status.diff.running": ("Comparing the working file with Git HEAD…", "正在比對工作檔案與 Git HEAD…"),
    "status.diff.ready": ("Git comparison ready", "Git 比對完成"),
    "status.diff.differences": ("Differences found.", "發現差異。"),
    "status.diff.same": ("No differences from Git HEAD.", "與 Git HEAD 版本相同。"),

    # Convert card
    "btn.choose_convert": ("Choose files to convert", "選擇要轉換的檔案"),
    "hint.convert_shortcut": ("Shortcut: Alt+C in File Explorer on one or more selected files.",
                              "快捷鍵：在檔案總管選取一或多個檔案後按 Alt+C。"),
    "label.quality": ("Quality", "品質"),
    "hint.convert_mode": ("auto = keep images/layout when LibreOffice is installed · "
                          "text = text-only · office = require LibreOffice",
                          "auto = 已安裝 LibreOffice 時保留圖片與版面 · "
                          "text = 只取文字 · office = 必須有 LibreOffice"),
    "status.convert.default": ("Select files, then pick a target format from the wheel.",
                               "先選擇檔案，再從格式輪挑選目標格式。"),
    "status.convert.none": ("No conversion is available for the selected files.",
                            "所選檔案沒有可用的轉換格式。"),
    "status.convert.busy": ("A conversion is already running.", "已有轉換正在進行。"),
    "status.convert.running": ("Converting {n} file(s) to {target}…", "正在把 {n} 個檔案轉換為 {target}…"),
    "status.convert.done": ("Converted {n} file(s) → {m} output file(s).",
                            "已轉換 {n} 個檔案，產生 {m} 個輸出檔。"),

    # Search card
    "btn.choose_folder": ("Choose folder", "選擇資料夾"),
    "btn.search": ("Search", "搜尋"),
    "col.type": ("Type", "類型"),
    "col.path": ("File", "檔案"),
    "status.search.default": ("Choose a folder to search recursively.", "選擇資料夾以遞迴搜尋。"),
    "status.search.ready": ("Ready to search.", "可以開始搜尋。"),
    "status.search.no_folder": ("Choose a folder first.", "請先選擇資料夾。"),
    "status.search.running": ("Searching…", "搜尋中…"),
    "status.search.found": ("{n} file(s) found.", "找到 {n} 個檔案。"),
    "status.search.explorer": ("Folder selected from File Explorer. Enter a filename or "
                               "choose a type, then click Search.",
                               "已從檔案總管選擇資料夾。輸入檔名或選擇類型後按「搜尋」。"),

    # Filter card
    "btn.apply_filter": ("Apply filter", "套用篩選"),
    "status.filter.default": ("Choose a folder and check formats to filter.",
                              "選擇資料夾並勾選要篩選的格式。"),
    "status.filter.ready": ("Ready to filter.", "可以開始篩選。"),
    "status.filter.running": ("Filtering…", "篩選中…"),
    "status.filter.found": ("{n} file(s) match the selected formats.",
                            "符合所選格式的檔案共 {n} 個。"),

    # AI card
    "check.ai_enable": ("Enable AI assistant", "啟用 AI 助手"),
    "field.base_url": ("Base URL", "服務位址"),
    "field.model": ("Model", "模型"),
    "field.api_key": ("API key", "API 金鑰"),
    "btn.save_ai": ("Save AI settings", "儲存 AI 設定"),
    "label.ai_instruction": ('Instruction (e.g. "move all PDF files in D:\\Docs to D:\\Archive")',
                             "指令（例如「把 D:\\Docs 內所有 PDF 移到 D:\\Archive」）"),
    "btn.run_ai": ("Run with AI", "用 AI 執行"),
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
    "action.search": ("Search files", "檔案搜尋"),
    "action.diff": ("Git comparison", "Git 比對"),
    "action.convert": ("Convert files", "檔案轉換"),
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
    "status.path.conflict": (" Another version takes precedence: {exe}; use py -m offlook.",
                             "（另一個版本優先：{exe}；請改用 py -m offlook。）"),

    # Footer and generic
    "btn.exit": ("Exit", "結束"),
    "btn.hide": ("Hide to tray", "隱藏到系統匣"),
    "status.initial": ("All files stay on your device. Nothing is uploaded.",
                       "所有檔案都留在你的電腦，不會上傳。"),
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

    # Conversion wheel
    "wheel.title": ("Convert to", "轉換為"),
    "wheel.count": ("{n} format(s)", "{n} 種格式"),

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
    "diff.title": ("Git comparison — {name}", "Git 比對 — {name}"),
    "diff.heading": ("{name} — working tree vs HEAD", "{name} — 工作目錄 vs HEAD"),
    "diff.subtitle": ("Working tree compared with HEAD", "工作目錄與 HEAD 版本比對"),
    "diff.legend": ("Added green · deleted red · modified amber",
                    "新增＝綠色 · 刪除＝紅色 · 修改＝琥珀色"),
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
