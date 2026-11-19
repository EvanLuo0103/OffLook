# 上傳到 GitHub 與組員協作

這份文件說明如何把 `OffLook-Modified` 上傳到 GitHub，以及組員要怎麼接手繼續改。

---

## 0. 先確認要上傳什麼

要上傳的是 **`OffLook-Modified` 這個資料夾**（73 個檔案），不是整個 `default-workspace`。
資料夾裡已經有 `.gitignore`，會自動排除 `__pycache__/`、`build/`、`*.egg-info/`、`.venv` 等不需要版本控制的東西。

> 使用者的設定檔（含 API key）存在 `%LOCALAPPDATA%\OffLook\config.json`，**不在專案資料夾內**，所以不會被上傳。

---

## 1. 安裝 Git（目前這台電腦還沒裝）

```powershell
winget install --id Git.Git -e --source winget
```

裝完 **關掉 PowerShell 再重開**（PATH 才會生效），然後確認：

```powershell
git --version
```

---

## 2. 設定你的身分（整台電腦只需做一次）

```powershell
git config --global user.name "你的名字"
git config --global user.email "你的email@example.com"
```

Email 建議用 GitHub 帳號的信箱，commit 才會正確歸屬到你。

---

## 3. 建立本機儲存庫並做第一次 commit

```powershell
cd "C:\Users\PC\Documents\deepseek-harness\default-workspace\OffLook-Modified"
git init -b main
git add .
git status
```

**先看 `git status` 的結果**，確認清單裡沒有 `__pycache__`、`*.egg-info`、`config.json` 之類的東西，再繼續：

```powershell
git commit -m "OffLook 0.3.0: 中文介面、UI 對比度改善、滑鼠滾輪捲動"
```

---

## 4. 在 GitHub 建立遠端儲存庫

1. 打開 https://github.com/new
2. **Repository name**：`offlook`（或 `offlook-project`）
3. **Visibility**：`Private`（還沒要公開就選這個）或 `Public`
4. **不要**勾選 "Add a README file"、"Add .gitignore"、"Choose a license"（本機已經有了，勾了會造成第一次 push 衝突）
5. 按 **Create repository**
6. 複製頁面上那條 `https://github.com/<你的帳號>/offlook.git`

---

## 5. 連接並推上去

```powershell
git remote add origin https://github.com/<你的帳號>/offlook.git
git push -u origin main
```

第一次 push 會跳出登入視窗。GitHub 已經不接受帳號密碼，要用 **Personal Access Token (PAT)** 當密碼：

1. GitHub → 右上頭像 → **Settings** → 左側最下方 **Developer settings**
2. **Personal access tokens** → **Tokens (classic)** → **Generate new token (classic)**
3. Note 隨便填（例如 `offlook-laptop`），Expiration 選 30 或 90 天
4. 勾選 **`repo`**（整個大項）→ **Generate token**
5. 複製那串 `ghp_...`（**只會顯示一次**）
6. 回到 PowerShell 的登入視窗：Username 填 GitHub 帳號，Password **貼上 PAT**

> 也可以改用 GitHub CLI，比較省事：
> ```powershell
> winget install --id GitHub.cli -e
> gh auth login
> ```
> 之後 push 就不用再輸入 token。

成功後整理一下遠端分支：

```powershell
git branch -u origin/main
```

---

## 6. 邀請組員

1. 進入你的 repo → **Settings** → 左側 **Collaborators**
2. **Add people** → 輸入組員的 GitHub 使用者名稱或 Email → 選取
3. 組員會收到 Email 邀請，**必須按接受**才會生效

組員權限說明：
- **Write**（Collaborators 預設）：可以直接 push
- 如果想強制走 Pull Request 審核，改用 **Branch protection rule**（Settings → Branches）

---

## 7. 組員怎麼接手

```powershell
git clone https://github.com/<你的帳號>/offlook.git
cd offlook
py -m pip install --user --only-binary=:all: -e .
py -m offlook
```

跑測試（109 個，全部是 `unittest`，**不需要 pytest**）：

```powershell
py -m unittest discover -s tests -v
```

補充需求（選用，只有部分轉換功能需要）：
```powershell
py -m pip install --user python-docx openpyxl python-pptx
```
以及選用的 LibreOffice（`office` 轉換模式用）。

### 測試環境注意

109 個測試裡有幾個需要「正常 Windows 環境」才跑得過，撿到下列訊息先別慌：

| 測試 | 需要什麼 |
| --- | --- |
| `test_search.test_compare_working_file_with_git_head` | 已安裝 Git（`git --version` 要有反應） |
| `test_windows_environment.*`、`test_windows_startup.*` | 可寫入 HKCU 登錄檔（一般使用者可以；被群組原則鎖住的環境不行） |
| `test_search.test_skips_symlinked_files` | 建立符號連結的權限（沒有的話會自動 skip，不算失敗） |
| `test_conversion.test_text_to_docx`、`test_pptx_text_mode_conversions` | 已安裝 `python-docx` / `python-pptx`（沒裝會自動 skip） |
| `test_worker_lifecycle.*` | 允許建立具名管道（正常桌面環境都允許） |

---

## 8. 日常協作流程（避免互相覆蓋）

**每次開工前**先同步：

```powershell
git pull
```

**每次做一個功能就開一個分支**：

```powershell
git switch -c feature/我的功能
# 改程式…
git add -A
git commit -m "feat: 加入 XXX 功能"
git push -u origin feature/我的功能
```

然後到 GitHub 上按 **Compare & pull request** → 請組員看一下 → **Merge**。

回到 main 並更新：

```powershell
git switch main
git pull
```

**兩個人在改同一個檔案時**：先 commit 自己的，再 `git pull --rebase`，解衝突後 `git push`。

---

## 9. 常見錯誤

| 訊息 | 原因與解法 |
| --- | --- |
| `remote origin already exists` | 已有遠端設定。改網址：`git remote set-url origin <新網址>` |
| `rejected ... non-fast-forward` | 遠端有你本機沒有的 commit。先 `git pull --rebase` 再 `git push` |
| `Authentication failed` | 用 PAT 當密碼，不是 GitHub 登入密碼 |
| `fatal: not a git repository` | 你不在專案資料夾內，先 `cd` 到 `OffLook-Modified` |
| `warning: LF will be replaced by CRLF` | 正常現象。想關掉：`git config --global core.autocrlf true` |
| 不小心 commit 了 `__pycache__` | `git rm -r --cached __pycache__` 後重新 commit |
| push 卡在大檔案 | 單檔超過 100 MB 會被拒。`build/`、`dist/` 不要上傳（`.gitignore` 已排除） |
| 想改最後一次 commit 訊息 | `git commit --amend`（已 push 過就不要用） |

---

## 10. 建議的 repo 設定（讓專案看起來完整）

- **About**（右上齒輪）：填一句描述，例如
  `Offline Windows file previewer with GUI and CLI — bilingual UI, mouse-wheel navigation`
- **Topics**：`python`、`tkinter`、`windows`、`file-preview`、`offline`、`i18n`
- **LICENSE**：已經有 MIT
- README 頂部已附上截圖（`docs/images/`）

---

## 11. 版本號提醒

`pyproject.toml` 目前標示 **0.3.0**，但這台電腦上已安裝的舊紀錄是 **0.1.0**。
重新安裝一次就會一致（`py -m offlook --version` 會顯示 0.3.0）：

```powershell
cd "C:\Users\PC\Documents\deepseek-harness\default-workspace\OffLook-Modified"
py -m pip install --user --only-binary=:all: -e .
py -m offlook --version
```
