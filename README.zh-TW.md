# OffLook

[English](README.md) | **繁體中文**

OffLook 是 Windows 的離線檔案預覽工具，提供圖形介面及命令列。預覽和檔案比較在本機執行；選用的 AI 檔案助手只會在你執行指令時連線到已設定的服務。

![OffLook 主視窗（繁體中文）](docs/images/main-window-zh.png)

使用右上角的 **中文 / English** 切換程式介面語言。

## 安裝與啟動

**不安裝 Python：** Windows x64 安裝程式發布後可從 [GitHub Releases](https://github.com/EvanLuo0103/OffLook/releases) 下載。安裝後從開始功能表開啟；可選擇將 `ol` 加入目前使用者的 PATH。

**已有 Python：** [PyPI 套件](https://pypi.org/project/offlook/) 發布後，使用 Windows 版 64 位元 Python 3.11–3.15（含 Tcl/Tk 與 Python Launcher）執行：

```powershell
py -m pip install --user offlook
py -m offlook
```

需要選用的 Python 轉換套件時，可安裝 `offlook[office]`。Microsoft Word 與 LibreOffice 仍需另外安裝。首發前可依[使用指南](docs/getting-started.md#1-download-and-install)從原始碼安裝。

## 預設快捷鍵

使用快捷鍵前，請保持 OffLook 執行。

| 快捷鍵 | 功能 |
| --- | --- |
| `Ctrl+Space` | 預覽檔案總管或桌面中選取的本機檔案。 |
| `Ctrl+Q` / `Ctrl+Alt+F` | 分別在主視窗或獨立小視窗開啟「搜尋與篩選」。 |
| `Ctrl+Alt+D` | 比較選取的兩個本機檔案。 |
| `Alt+C` | 開啟獨立轉換視窗，不喚起主視窗。 |
| `Ctrl+Alt+Shift+A` | 開啟 AI 檔案助手小視窗，不必選取檔案。 |

在「設定 → 快捷鍵設定」修改按鍵；按 F1 查看內建說明及快捷鍵註冊狀態。

## 命令列範例

舊版安裝需重新安裝才能取得 `ol`。若找不到 `ol`，請在設定中將 OffLook 加入 PATH，然後重新開啟 PowerShell。

```powershell
ol preview '.\README.md'
ol --background
ol search --name report --kind pdf
ol compare before.txt after.docx
ol convert '.\README.md' --to pdf
ol filter '.\docs' --kind markdown
ol filter '.\docs' --gui --kind markdown
```

## 文件

- [使用指南（英文）](docs/getting-started.md)：安裝、操作、支援格式與快捷鍵排查。
- [命令列參考（英文）](docs/getting-started.md#7-command-line-reference)：參數和結束代碼；也可以執行 `ol --help`。
- [Python API 參考（英文）](docs/api.md)：設定、事件、檔案操作與擴充介面。

執行時依賴列於 `requirements.txt`，套件與命令入口定義於 `pyproject.toml`。OffLook 採用 [MIT 授權](LICENSE)。
