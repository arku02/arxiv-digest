# 開發期間的路徑隱私保護

程式仍使用真實路徑執行。工具只對公開輸出做去識別化，不改寫原始碼、測試斷言或可執行設定。此功能針對私人檔案路徑，不是通用密碼／個資掃描器，也不是零洩漏保證。

## 1. 每個本機倉庫啟用一次

接入型專案在專案根目錄執行：

```text
node .integration/scripts/privacy.mjs install
node .integration/scripts/privacy.mjs history
```

平面 starter 將 `.integration/scripts/` 換成 `scripts/`，或使用 `npm run privacy:install` 與 `npm run privacy:history`。

先有 Git 倉庫才能安裝。安裝只增加本機 pre-commit、commit-msg、pre-push hooks，不修改全域設定、不提交、不推送。既有 hooks 或 `core.hooksPath` 會令安裝停止且保留原設定，需將對應檢查命令整合到原 hooks。導入工具不會暗中變更 Git 設定；複製模板、安裝依賴或 clone 本身不代表 hooks 已啟用。每台電腦、每個 clone 都必須執行一次啟用。

提交時檢查完整 Git index 的實際內容，不以工作目錄的檔案代替。推送時檢查本次要推送的分支／標籤可到達的完整歷史，包括舊版檔案、提交訊息與標籤文字；刪除遠端分支沒有新增內容可掃描。首次 `history` 可提早找出舊資料問題，不會自動改寫歷史。

## 2. 本機設定與公開設定分開

`workflow.config.json` 保留可共用的 `python` 或有效專案相對路徑。若 Python 只裝在個人位置，建立不納入版控的 `workflow.local.json`：

```json
{
  "pythonExecutable": "在本機填入實際 Python 執行檔位置",
  "privateRoots": []
}
```

`pythonExecutable` 必須替換成真實可執行路徑，不能保留上面的說明文字。`privateRoots` 可填不位於家目錄的私人資料夾絕對路徑。這份本機設定不要上傳；即使強制加入 Git，攔截器仍會阻擋。

Python 選擇順序：`WORKFLOW_PYTHON` 環境變數 → `workflow.local.json` → 共用設定。有效設定只參與驗證的新鮮度雜湊，不將其私人路徑寫入公開證據。切換執行環境後需要重新 verify，避免沿用不同環境的通過結果。

## 3. 證據與除錯

- `.workflow/evidence/` 的新日誌先去識別化，再計算 `logHash`；JSON 的命令只供說明，不用於再次執行。
- 測試通過／失敗及案例數根據真實原始輸出判斷，去識別化不會把失敗變成成功。
- 原始日誌留在本機 `.workflow/private/`，供除錯使用；該目錄、導入復原資料 `.workflow/imports/` 與本機設定會被忽略及攔截。
- `.gitattributes` 保留公開證據的原始換行位元組，避免 Git 換行轉換造成雜湊失效。
- 新工具不回頭修改舊封存證據；舊資料若被攔截，依去識別化規則整理，不能手改雜湊或通過結果來消除阻擋。

## 4. 被攔截時

輸出只列檔名、物件編號與原因，不重印匹配到的私人路徑內容。檔名本身若含私人路徑也會處理。

先判斷它是文件路徑、本機設定還是歷史證據，再做相應修正；工具不會自動替換原始碼，也不會改動已暫存內容。不要使用 `--no-verify` 當日常解法。

對確定可公開的假路徑測試樣本、圖片等非文字資產，可在專案根目錄建立 `privacy-allowlist.json`：

```json
[
  {
    "file": "assets/logo.png",
    "sha256": "填入審查後檔案的完整 SHA-256（64 個小寫十六進位字元）",
    "reason": "已檢查內容與中繼資料，可公開"
  }
]
```

這是人工審查後的精確例外，不是自動批准。檔案內容一變，例外失效；不接受目錄或萬用字元。提交檢查使用已暫存的例外檔，推送／歷史檢查使用目前本機的例外檔。私人設定與原始日誌不能用例外放行。此版本會阻擋 Git LFS 與 submodule；它們的實際內容需要另外建立檢查流程，不能只批准指標檔。

## 5. 限制

預設辨識目前專案／家目錄／Node 執行檔、指定私人根目錄、Windows 磁碟路徑、常見使用者家目錄與 UNC 路徑，並檢查常見 JSON 跳脫及 URL 編碼。未知格式、加密、壓縮或刻意編碼內容不能保證辨識。二進位或非 UTF-8 內容需精確審查例外；單物件超過 8 MiB、歷史超過 50000 個物件、淺層歷史或掃描失敗會阻擋，不能視為通過。

完整歷史檢查會隨專案成長變慢；此版本優先不漏查舊提交，尚未加入快取。hooks 可被停用或繞過；從網站直接上傳、使用不執行 hooks 的工具、或上傳打包附件，都不受這些本機 hooks 保護。GitHub 上的檢查發生在資料已上傳之後，不能取代本機檢查。

Git hook 行為依據：[Git 官方文件](https://git-scm.com/docs/githooks)。
