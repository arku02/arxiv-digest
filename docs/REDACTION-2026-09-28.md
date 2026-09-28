# 舊驗證紀錄去識別化紀錄

日期：2026-09-28。依 [專案工作規則](../PROJECT-RULES.md)「歷史證據與隱私」，將工具升級前產生的驗證紀錄中的個人電腦路徑換成通用標記，作為可公開的去識別化副本。純紀錄整理，未新增產品行為。同日另行改寫 Git 歷史並改用新 repo，見下方「Git 歷史改寫」。

## 原因

升級到模板 0.2.0 後（見 [升級紀錄](MAINTENANCE-2026-09-28-template-0.2.md)），唯讀路徑掃描發現 18 份舊紀錄含本機家目錄下的絕對路徑，會讓之後啟用的提交／推送檢查攔下。新版工具只處理新證據，不回頭修改舊紀錄，因此另行整理。

## 影響檔案（18 份）

- `.workflow/evidence/`：add-feedback-collect、add-push-translation、add-telegram-push、clarify-retry-message、fix-announce-lag、fix-fetch-checkpoint、fix-translation-simplified 的 `.json`
- `.workflow/receipts/`：同上 7 個變更的 `.json`
- `.workflow/maintenance/2026-09-27/`：`offline-tests.json`、`spec-validation.json`
- `.workflow/maintenance/2026-09-27-docs-sync/`：`offline-tests.json`、`spec-validation.json`

未修改：`.workflow/evidence/*.log`（本來就不含個人路徑）、`.workflow/baselines/`、兩份 `summary.json`、`openspec/` 封存內容。

## 替換類別

| 標記 | 代表 | 次數 |
|---|---|---|
| `<PROJECT_ROOT>` | 本專案根目錄 | 24 |
| `<TRIAL_COPY_ROOT>` | 2026-09-18 模板試驗期間的隔離試驗副本根目錄，不是本專案 | 7 |
| `<LOCAL_PATH>` | 本機 Python 執行檔 | 9 |

`<PROJECT_ROOT>`、`<LOCAL_PATH>` 與新版工具產生的標記相同。`<TRIAL_COPY_ROOT>` 是本次新增，用來保留「clarify-retry-message、fix-fetch-checkpoint 是在試驗副本中驗證與封存」這個事實，避免誤讀成原專案的結果。

只替換路徑前綴，路徑其餘部分（例如 `.workflow\python-….json`）與原本的分隔符號保留。每份檔案開頭新增 `publicCopy` 欄位，標示為公開去識別化副本、替換了哪些標記及本紀錄位置。

## 驗證

- 18 份檔案都能解析為 JSON；移除 `publicCopy` 後，與原檔「套用相同路徑替換」的結果完全相同，欄位順序不變。也就是說，`passed`、測試數、`executedIds`、`digest`、`verifiedDigest`、`logHash`、時間與規格驗證結果都沒有改動。
- 7 份證據的 `logHash` 仍與對應 `.log` 檔的 SHA-256 相符（`.log` 未修改）。
- 修改後以 `scripts/privacy.mjs` 掃描這 18 份檔案，已沒有路徑問題。
- 每份檔案的原始與公開副本 SHA-256 列於 [雜湊清單](../.workflow/maintenance/2026-09-28-redaction/manifest.json)。

## 限制

- 這些是公開去識別化副本，不是原始逐位元組證據。檔案內的 `digest`、`logHash` 等欄位指的是當時的原始執行，不適用於修改後的 JSON 檔本身；清單中的 `publicCopySha256` 只用來辨識公開副本。
- 原始檔案保存在本機 `_local-backups/2026-09-28-redaction/`（不進版控），以及保留為私人唯讀的原 repo（見下節），可用清單中的 `originalSha256` 核對。
- 這次沒有重跑任何舊變更的 verify／archive，也沒有把新測試結果回填到舊紀錄。

## Git 歷史改寫

原因：專案之後預計公開，舊版紀錄、舊版 `README.md` 與 `workflow.config.json` 在 Git 歷史中仍含個人路徑，只改現行檔案無法移除。依 PROJECT-RULES，改寫歷史需另行確認，使用者已於 2026-09-28 同意。

做法：

- 在另一份複本上以 `git filter-branch --tree-filter` 改寫全部 12 個提交；原資料夾與原 repo 不動。
- 替換規則與上表相同，另加兩種情況：舊版 `README.md` 排程範例中的路徑（單一反斜線寫法）同樣換成 `<PROJECT_ROOT>`／`<LOCAL_PATH>`；舊版 `workflow.config.json` 的 `pythonExecutable` 換成可執行的 `python`，不填標記。
- 歷史中的舊版紀錄只替換路徑，不補 `publicCopy` 欄位；`publicCopy` 只出現在本次整理之後的版本。
- 改寫後推送到新建的私人 repo，之後在新 repo 開發。原 repo 改名為 `arxiv-digest-original`，保持私人並設為唯讀封存，保存未改寫的原始歷史，不再推送。

驗證：

- 新舊 12 個提交逐一比對：作者、提交者、時間與提交訊息完全相同；每個提交只有上述檔案不同，且所有不同的行都只是路徑換成標記或 `python`。
- 最新提交的檔案內容與改寫前完全相同。
- 刪除指向舊提交的參照並清除後，`scripts/privacy.mjs history` 掃描完整歷史 340 個物件，結果 0 筆。

### 提交編號對照

封存變更的 `design.md` 以「來源 commit」記錄當時的編號，這些封存檔維持原文不改。舊編號只能在原 repo 查到；新 repo 中對應的提交如下：

| 原編號 | 新編號 | 提交 | 被引用於 |
|---|---|---|---|
| 91c287e | 94f8fc4 | feat: 專案骨架與每日增量抓取 | |
| 27c5ef4 | c98b352 | docs: 補上實測數據，修正安裝與排程說明 | 2026-09-18-fix-fetch-checkpoint |
| 30036e0 | 63ccebf | Preserve fetch checkpoint fixes and organize project workflow records | 2026-09-27-fix-announce-lag |
| ed4831b | e8a11d3 | fix: daily 回看 4 天，補上公告前查不到的論文 | 2026-09-27-add-telegram-push |
| 8998a5d | 4bc6583 | feat: Telegram 每日推送與回饋按鈕 | 2026-09-27-add-feedback-collect |
| 3237b8d | fddbbb6 | feat: 收集 Telegram 按鈕回饋並顯示回饋率 | 2026-09-27-add-push-translation |
| 3fccf34 | 77cfe9e | feat: 推送訊息以本機 Ollama 翻成繁體中文 | 2026-09-27-fix-translation-simplified |
| 7e1ca2c | c9b4439 | fix: 修正翻譯結果中混入的簡體字與大陸用語 | |
| 714f8bd | 6ba7099 | docs: 同步當天五個變更後的文件與設定範例 | |
| 25a9d4e | c226030 | docs: 允許有紀錄的隱私去識別化，不得竄改歷史事實 | |
| df8b055 | e10e56b | chore: 工作流程工具升級到模板 0.2.0 路徑隱私版本 | |
| f5fa936 | d37fb1d | chore: 舊驗證紀錄改為公開去識別化副本 | |

限制：改寫後的提交是去識別化版本，不是原始逐位元組歷史；舊提交中的檔案雜湊與原 repo 不同。原 repo 若被刪除，原始歷史只剩本機備份。
