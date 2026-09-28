# 舊驗證紀錄去識別化紀錄

日期：2026-09-28。依 [專案工作規則](../PROJECT-RULES.md)「歷史證據與隱私」，將工具升級前產生的驗證紀錄中的個人電腦路徑換成通用標記，作為可公開的去識別化副本。純紀錄整理，未新增產品行為，未改寫 Git 歷史。

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
- 原始檔案保存在本機 `_local-backups/2026-09-28-redaction/`（不進版控），也仍存在於本次提交之前的 Git 歷史中，可用清單中的 `originalSha256` 核對。
- Git 歷史中的舊版紀錄、舊版 `README.md` 與 `workflow.config.json` 仍含個人路徑。推送前檢查會掃描要推送分支的完整歷史，因此在處理 Git 歷史之前啟用 hooks 仍會攔下推送。是否改寫歷史與強制推送需另行決定。
- 這次沒有重跑任何舊變更的 verify／archive，也沒有把新測試結果回填到舊紀錄。
