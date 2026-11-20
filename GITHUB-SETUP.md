# 上傳到 GitHub 與組員協作

這份文件說明如何在 Windows 安裝 OffLook、執行測試，以及使用 GitHub 分支與 Pull Request 協作。OffLook 的本機檔案比對不需要 Git、GitHub 帳號或儲存庫。

---

## 1. 從現有儲存庫開始

使用 Windows PowerShell、64 位元 Python 3.11–3.15（含 Tcl/Tk）與 [Git for Windows](https://git-scm.com/download/win)。如果儲存庫是私人的，先接受擁有者的 GitHub 邀請。

### 安裝 Git（尚未安裝時）

```powershell
winget install --id Git.Git -e --source winget
```

安裝後重開 PowerShell，執行 `git --version` 確認 Git 可用。

### Clone 並啟動 OffLook

用 GitHub 的 **Code** 選單複製儲存庫網址。將下面的 `<repository-url>` 換成該網址，`<clone-directory>` 換成 clone 建立的資料夾名稱：

```powershell
git clone "<repository-url>"
cd "<clone-directory>"
py -m pip install --user --only-binary=:all: -e .
py -m offlook
```

若已 clone，只需進入既有的專案根目錄（含 `pyproject.toml`）後安裝，不必再 clone 或執行 `git init`。不要把 ZIP 快照覆蓋到現有 clone。

> 預設的使用者設定檔在 `%LOCALAPPDATA%\OffLook\config.json`。API key 以明文存在該 JSON 中；不要把設定檔或金鑰複製到儲存庫。

### HTTPS 登入

使用 Git for Windows 提供的 **Git Credential Manager**，依 `git clone` 或 `git push` 的提示在瀏覽器登入。若使用 [GitHub CLI](https://cli.github.com/)，可先執行：

```powershell
gh auth login --hostname github.com --git-protocol https
gh auth setup-git
```

---

## 2. 設定你的身分（整台電腦只需做一次）

```powershell
git config --global user.name "你的名字"
git config --global user.email "你的email@example.com"
```

Email 建議用 GitHub 帳號的信箱，commit 才會正確歸屬到你。

---

## 3. 首次發布尚未初始化的本機專案（選用）

只有當本機專案還沒有 Git 歷史，且要發布到新的 GitHub 儲存庫時，才使用本節。若要接手現有 GitHub 儲存庫，請使用第 1 節。先在 PowerShell 進入含 `pyproject.toml` 的專案根目錄：

```powershell
cd "<project-directory>"
git init -b main
git add .
git status
```

先檢查 `git status` 裡準備提交的檔案，確認沒有設定檔、金鑰、虛擬環境或打包產物，再提交：

```powershell
git commit -m "Initial OffLook import"
```

### 建立 GitHub 遠端儲存庫

1. 打開 [GitHub 的新建儲存庫頁面](https://github.com/new)，填寫儲存庫名稱並選擇 `Private` 或 `Public`。
2. 不要勾選建立 `README`、`.gitignore` 或 `LICENSE`；本機已經有這些檔案，遠端請保持空白。
3. 按 **Create repository**，複製頁面提供的 HTTPS 網址。

### 連接並推送

```powershell
git remote add origin "<repository-url>"
git push -u origin main
```

將 `<repository-url>` 換成剛複製的網址；需要登入時使用第 1 節的 HTTPS 登入方式。

---

## 4. 邀請組員

1. 進入你的 repo → **Settings** → 左側 **Collaborators**
2. **Add people** → 輸入組員的 GitHub 使用者名稱或 Email → 選取
3. 組員會收到 Email 邀請，**必須按接受**才會生效

組員權限說明：
- **Write**：可以推送分支。若要要求以 Pull Request 審核後才能合併至 `main`，請為 `main` 設定分支保護規則。

---

## 5. 執行測試

在專案根目錄執行下列指令；`pytest` 會收集既有的 `unittest` 測試與 pytest 測試函式：

```powershell
py -m pip install --user pytest
py -m pytest tests
```

`python-docx` 是專案安裝時一併安裝的執行依賴，不用另外安裝。只有使用對應的轉換功能或執行相關測試時，才需要選裝 `python-pptx`、`openpyxl` 或 `docx2pdf`；需要 LibreOffice 的轉換模式則須另外安裝 LibreOffice。各格式所需的後端請見[入門指南](docs/getting-started.md)。

### 測試環境注意

完整的 Windows 整合測試請在有 Tcl/Tk 的互動式 Windows 桌面，以一般使用者帳號執行。受限環境可能阻擋下列操作：

| 測試 | 需要什麼 |
| --- | --- |
| `test_windows_environment.*`、`test_windows_startup.*` | 可寫入 HKCU 登錄檔（一般使用者可以；被群組原則鎖住的環境不行） |
| `test_search.test_skips_symlinked_files` | 建立符號連結的權限（沒有的話會自動 skip，不算失敗） |
| `test_conversion.test_text_to_docx`、`test_pptx_text_mode_conversions` | DOCX 使用專案一併安裝的 `python-docx`；PPTX 測試需要選裝 `python-pptx` |
| `test_worker_lifecycle.*` | 允許建立具名管道 |

---

## 6. 日常協作流程（避免互相覆蓋）

**每次開工前**先同步：

```powershell
git switch main
git pull --ff-only
```

**每次做一個功能就開一個分支**：

```powershell
git switch -c feature/my-feature
# 改程式…
git add -A
git commit -m "feat: 加入 XXX 功能"
git push -u origin feature/my-feature
```

然後到 GitHub 上按 **Compare & pull request** → 請組員看一下 → **Merge**。

回到 main 並更新：

```powershell
git switch main
git pull --ff-only
```

若 Pull Request 與 `main` 有衝突，先提交分支上的變更，再在功能分支執行 `git fetch origin` 與 `git merge origin/main`，解決衝突後推送分支。

---

## 7. 常見錯誤

| 訊息 | 原因與解法 |
| --- | --- |
| `remote origin already exists` | 先用 `git remote -v` 確認既有遠端；若確定要改網址，執行 `git remote set-url origin "<repository-url>"`。 |
| `rejected ... non-fast-forward` | 先 `git fetch origin` 檢查遠端的提交，整合後再推送；不要用強制推送覆蓋組員的提交。 |
| `Authentication failed` | 使用第 1 節的 HTTPS 登入方式，並確認登入的帳號有儲存庫權限。 |
| `fatal: not a git repository` | 先切換到 clone 下來的儲存庫資料夾。 |
| push 卡在大檔案 | GitHub 會拒絕大於 100 MiB 的單檔。不要提交 `build/`、`dist/` 等打包產物。 |
| 想改最後一次 commit 訊息 | `git commit --amend`（已 push 過就不要用） |

---

## 8. 建議的 repo 設定（讓專案看起來完整）

- **About**（右上齒輪）：填一句描述，例如
  `Offline Windows file previewer with GUI and CLI — bilingual UI, mouse-wheel navigation`
- **Topics**：`python`、`tkinter`、`windows`、`file-preview`、`offline`、`i18n`
- **LICENSE**：已經有 MIT
- README 頂部已附上截圖（`docs/images/`）

---

## 9. 確認安裝版本

`pyproject.toml` 宣告的版本是 `0.3.0`。`py -m offlook --version` 讀取 `py` 所選 Python 解譯器已安裝的套件中繼資料，不會直接讀取工作目錄中的 `pyproject.toml`。要核對本專案的版本，先在專案根目錄重新安裝，再用同一個解譯器查詢：

```powershell
py -m pip install --user --only-binary=:all: -e .
py -m offlook --version
```
