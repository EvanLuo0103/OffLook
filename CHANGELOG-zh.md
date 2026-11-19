# 修改說明（OffLook-Modified）

- **專案**：OffLook（Windows 離線檔案預覽器，Python + Tkinter）
- **版本**：`0.1.0` → **`0.3.0`**
- **原始碼位置**：`src/offlook/`
- **說明**：以下每一項都能對應到 commit，方便組員 review 與報告引用。

---

## 一、修正：主視窗完全開不起來（嚴重）

**問題**
`gui.py` 建立「Convert files」卡片的 Quality 下拉選單時寫成：

```python
ttk.Combobox(..., command=self._convert_mode_changed)
```

但 `ttk::combobox` 沒有 `-command` 這個選項（只有 `-postcommand`），所以建立主視窗時直接拋出

```
TclError: unknown option "-command"
```

程式被 `cli.py` 包成「OffLook could not create the preview window」，整個 App 無法使用。

**做法**
改用 Combobox 的標準虛擬事件，並讓處理函式接受事件參數：

```python
quality_box = ttk.Combobox(..., values=('auto', 'text', 'office'))
quality_box.bind('<<ComboboxSelected>>', self._convert_mode_changed)
```

```python
def _convert_mode_changed(self, _event=None):
```

**影響檔案**：`src/offlook/gui.py`

**附帶效果**：原本「改 Quality 後自動存檔」的功能其實從來沒被觸發過，現在才會真的運作。

---

## 二、新增：滑鼠滾輪捲動（主視窗 + 預覽視窗）

**問題**
主視窗只能用右側滾軸捲動；預覽視窗則是「指標在文字上可以滾、在標題或檔案路徑欄上完全沒反應」，因為 Tk 是把滾輪事件交給指標下面的那個元件。

**做法**

1. **主視窗**：在 Toplevel 綁定 `<MouseWheel>`（`_bind_mousewheel` / `_wheel_main`），把滾輪事件換算成格數後呼叫 `main_canvas.yview_scroll()`。
   - 支援精細滾輪／觸控板：一格是 `delta=120`，不滿一格（例如 `delta=30`）也走一步，不會被忽略。
   - **串接式捲動**：結果表或文字框還有隱藏內容時自己捲；已經捲到底就改成捲動整個頁面，不會出現「滾輪沒反應」。
   - 下拉選單保留原生行為（滾輪是切換選項）。
   - 滾軸本身直接綁定同一個處理函式並回傳 `"break"`，避免它原本一次跳 4 格，讓全視窗速度一致。
2. **預覽視窗**：新增 `PreviewWindow._wheel()`，記住當前內容的捲動目標（文字／表格／資訊卡畫布）；指標在標題、路徑欄、置頂勾選框、狀態列上也能捲動內容。文字類每次 3 行（與 Tk 原生手感一致）。

**影響檔案**：`src/offlook/gui.py`、`src/offlook/preview/window.py`

---

## 三、改善：按鈕與背景難以分辨（UI 對比度）

**問題**
按鈕是 `relief="flat"`、沒有填色，邊框色 `#DCE3ED` 又幾乎等於背景 `#F4F6FA`，使用者看不出哪些東西可以按。

**做法**（`src/offlook/ui/theme.py` 重調）

| 元素 | 修改前 | 修改後 |
| --- | --- | --- |
| 視窗背景 | 近白色 | 冷灰 `#EDF1F8`，白色卡片明顯浮起 |
| 卡片 | 無邊框 | 1px 邊框 `#C7D2E4` |
| 一般按鈕 | 平面、無填色 | 白底 + 明顯邊框 `#9FB0C9`，滑過淡藍、按下更深 |
| 主要動作 | 只有「選擇檔案」是藍色 | 實心藍 + 深藍邊框，hover／pressed 三態分明 |
| 輸入框／下拉選單 | 細邊框 | 白底 + 1px 框，聚焦變藍框，下拉箭頭改藍色 |
| 滾軸 | 幾乎看不見 | 明顯的槽與滑塊，滑過加深 |
| 結果表格 | 無邊框 | 1px 框 + 淡藍表頭 + 可讀的選取色 |

**影響檔案**：`src/offlook/ui/theme.py`

---

## 四、新增：中／英介面切換

**做法**

1. 新增 `src/offlook/ui/i18n.py`：**151 條**字串，中英並排在同一張表（key: (English, 中文)），提供 `tr()`、`tr_in()`、`set_language()`、`normalize_language()`，以及給測試用的 `missing()`（可驗證沒有漏翻的 key）。
2. `core/config.py` 新增設定欄位 `language`（`"en"` / `"zh"`），會寫進原本的 JSON 設定檔，**重開程式仍記得**。
3. 主視窗右上角新增 **`中文`｜`English`** 分段按鈕（就在「說明」右邊），點一下立即切換並存檔。
4. 切換時**重建主視窗**，但所有數值都存在 `StringVar` 裡（已輸入的資料夾、AI 設定、快捷鍵草稿、搜尋結果都會保留）；搜尋／篩選結果會重新填入，未改動的提示文字會換語言，真正的訊息（錯誤、筆數）不會被覆蓋。
5. 翻譯範圍：主視窗全部卡片／按鈕／提示／狀態／快捷鍵狀態、預覽視窗（標題列、頁尾、檔案資訊卡）、內建說明（F1，**完整中文版**）、格式輪、Git 比對視窗。

**影響檔案**：`src/offlook/ui/i18n.py`（新增）、`src/offlook/gui.py`、`src/offlook/preview/window.py`、`src/offlook/ui/help.py`、`src/offlook/ui/convert_wheel.py`、`src/offlook/ui/diff.py`、`src/offlook/core/config.py`、`src/offlook/ui/theme.py`

---

## 五、修正：`src/offlook.egg-info` 殘留導致「加入 PATH」失效

**問題**
專案裡留著打包產物 `src/offlook.egg-info`。它會蓋掉 `importlib.metadata` 對 `offlook` 的解析，使 `resolve_offlook_scripts_dir()` 找不到 `offlook.exe`，按「Add to PATH」只會得到

```
Cannot identify a unique offlook.exe in the installation records.
```

**做法**
刪除 `src/offlook.egg-info`（此類產物本來就被 `.gitignore` 排除，不應進版控）。修好後可正確解析到
`C:\Users\<使用者>\AppData\Roaming\Python\Python312\Scripts`。

---

## 六、修正：測試檔過期（期待 3 個快捷鍵動作，實際有 4 個）

**問題**
原作者後來新增了「檔案轉換」快捷鍵（`convert_hotkey`），但 `tests/test_shortcut_integration.py` 仍寫死 `len(listeners) == 3` 與 `{'preview','diff'}` 這類集合，因此**原始版本跑起來就有 11 個測試失敗**（已在 `OffLook-main` 上實測確認）。

**做法**
把測試更新為 4 個動作（`len == 4`、集合補上 `'convert'`）。修正後 11 個測試全數通過。

**影響檔案**：`tests/test_shortcut_integration.py`

---

## 七、文件與版本

| 檔案 | 內容 |
| --- | --- |
| `pyproject.toml` | 版本 `0.3.0`，描述標註 modified build |
| `README.md` | 語言切換說明、滾輪說明、介面截圖 |
| `docs/api.md` | 新增 `language` 設定欄位說明 |
| `docs/images/` | 4 張介面截圖（中／英／說明／預覽） |
| `MODIFICATIONS.md` | 完整英文修改紀錄 |
| `GITHUB-SETUP.md` | 上傳 GitHub 與協作流程 |

---

## 八、測試結果

**專案內建測試（109 個，`unittest`）**
在正常 Windows 環境下應全數通過。開發機（受限制的沙箱）實測為 **84 通過 / 22 因環境限制無法執行 / 3 自動跳過**，22 個全是環境因素：

| 原因 | 數量 |
| --- | --- |
| 未安裝 Git | 1 |
| 無法寫入 HKCU 登錄檔（PATH、開機啟動測試） | 15 |
| 無法建立具名管道（預覽 worker 測試） | 6 |

**另外補做的驗證**

| 項目 | 結果 |
| --- | --- |
| 預覽渲染（文字／Markdown／程式碼／CSV／PNG／PDF 兩頁／docx／二進位／空檔／超大檔／停用副檔名／速度） | 13/13 通過 |
| 文件轉換（docx→txt、txt→docx、xlsx→csv/txt、pptx→txt/docx、目標格式計算） | 11/11 通過 |
| CLI（`--version`、`--help`、缺參數、config 不存在） | 通過（退出碼 0/2 正確） |
| 滑鼠滾輪（真實滑鼠輸入 12 項） | 全數通過 |
| 語言切換（來回切換、151 條字串無缺漏、設定持久化） | 全數通過 |
| `compileall` + 實際啟動 | 通過 |

---

## 九、組員需要注意的行為變更

1. **設定檔多了 `language` 欄位**：舊的 `config.json` 沒有這個欄位也能載入（預設 `en`），不會壞。
2. **`--version` 會顯示 0.3.0**：需重新安裝才生效（`py -m pip install --user --only-binary=:all: -e .`）。
3. **Quality 下拉現在會存檔**：以前不會（因為 bug）。
4. **「加入 PATH」修好了**：以前在 editable 安裝下必失敗。
5. **說明視窗（F1）會跟著介面語言**切換，內容為完整中文版。
6. 檔案系統／設定類的**錯誤訊息仍是英文**（刻意保留，因為它們引用路徑與設定細節）。

---

## 十、修復：合併組員的「預覽視窗手動縮放」（曾被我方覆蓋）

**問題**
本專案是以 GitHub 上的 **ZIP 快照**為基礎修改的，而組員在我下載之後又推了一個 commit：

```
9ebdc77  Add manual zoom controls to preview window   (作者 Anson-pb)
```

把整份檔案覆蓋進 clone 時，`src/offlook/preview/window.py` 被我們的版本整檔取代，**該 commit 的縮放功能因此消失**（`git grep zoom HEAD` 找不到任何結果）。

**做法**
把該功能完整合併回我們的版本，並與本專案新增的滾輪整合：

| 元件 | 行為 |
| --- | --- |
| `_zoom` | 100% 起算，範圍 25%–400%，每次 ±25% |
| `+` / `−` 按鈕 | 調整倍率，並以 `bounded_viewport` 重新向 worker 要求更高解析度的圖（不是把舊圖放大） |
| `Fit` / `適應` | 回到 100%（隨介面語言翻譯） |
| 圖片畫布 | 縮放後超出視窗時可**用滾輪或捲軸**平移（與第十一節的滾輪功能共用 `_wheel_target`） |
| 頁面導覽列 | 顯示時機調整為「PDF 或有圖片」；純文字／表格時隱藏縮放控制 |

**影響檔案**：`src/offlook/preview/window.py`、`src/offlook/ui/i18n.py`

**驗證**：11 項檢查全數通過（控制項顯示、倍率、放大後尺寸、上限、畫布可捲動、滾輪可捲動縮放後的圖片、Fit 還原、純文字時隱藏控制項）。

**教訓（流程面）**
以 ZIP 下載的程式碼**沒有 Git 歷史**，直接覆蓋會悄悄刪掉組員的 commit。正確做法是：`git clone` 之後再改，或至少先把 clone 的變更合併回自己的版本再 push。本專案的 `setup-github.ps1` 已改為**偵測到 clone 已存在就停止**，避免再次覆蓋。

