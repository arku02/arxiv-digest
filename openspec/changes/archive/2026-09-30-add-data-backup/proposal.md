# 回饋資料備份到私人 repo

## Why
使用者按的 👎👍⭐ 只存在本機 MySQL 的 feedback 表，Git 與專案資料夾都不包含資料庫。電腦故障或資料庫被刪時，回饋無法重建；P3 要用這些回饋評估與訓練模型，資料遺失的代價高。

事實（2026-09-30）：
- 程式只把回饋寫進資料庫，沒有任何匯出功能；repo 內沒有回饋資料檔。
- 使用者已建立私人 GitHub repo arku02/arxiv-digest-data（未登入狀態查詢 API 回 404），並同意把回饋備份到這個 repo，而不是放進可能公開的 arxiv-digest。
- 論文本身可依 arxiv_id 從 arXiv 重新取得，推送與回饋紀錄則無法重建。

成功標準：每天排程執行後，私人 repo 內有一份與資料庫一致的推送與回饋紀錄；資料沒變時不產生新提交；推送失敗時下次會補上。

## What Changes
- 新增 backup 指令：把每篇已推送論文的 arxiv_id、標題、分類、發表日、批次資訊、推送時間與回饋標籤匯出成 pushes.csv，寫到備份資料夾。
- 備份資料夾必須是 git 工作目錄；檔案有變動才提交，每次都嘗試 git push，讓先前推送失敗的提交補上。
- 新增選用的 [BACKUP] 設定（dir、push），預設為專案旁的 arxiv-digest-data 資料夾。
- 不匯出 chat_id 與 message_id：P3 用不到，且 chat_id 是個人帳號識別碼。
- 採 full：新增能力，且會對外部 Git 遠端寫入。

## Non-goals
- 不備份整個資料庫、論文摘要全文或作者表；不提供從 CSV 還原資料庫的指令。
- 不建立或設定遠端 repo、不處理 Git 認證；沿用本機 Git 的憑證設定。
- 不修改 Windows 排程；新增排程動作由使用者以系統管理員權限執行。

## Capabilities
### New Capabilities
- data-backup: 匯出推送與回饋紀錄並提交、推送到指定的 git 工作目錄。
### Modified Capabilities
- 無

## Impact
store.py、config.py、cli.py、新增 backup.py、config.ini.example、README.md；新增 tests/test_data_backup.py 並登錄於 workflow.config.json。

每次 backup 讀取 pushes、push_batches、papers、feedback 四張表，約每天增加 10 列；對遠端的寫入只有 git push。
