# 技術設計

## 已知事實
- 推送紀錄在 pushes（batch_id、paper_id、chat_id、message_id、pushed_at），批次在 push_batches（pool_size、sent、status），回饋在 feedback（paper_id UNIQUE、label、created_at；改按只更新 label）。見 store.py SCHEMA_STATEMENTS 與 save_feedback。
- feedback 只接受對得上推送紀錄的點擊（feedback-collect R2），所以每筆回饋都對應一筆推送。
- 設定檔位於專案根目錄的 config.ini；其他區段採「保存原始字串、用到時才驗證」的做法，填錯不影響其他指令。
- 本機 Git 已有 arku02 的身分與 GitHub 憑證；私人 repo 已 clone 到專案旁的 arxiv-digest-data（2026-09-30，空 repo，預設分支 main）。

## 假設與待決問題
- 假設排程執行時本機 Git 憑證可用（與使用者平常推送相同）；失敗時依 R2 保留本機提交，下次補推。
- 無待決業務問題。備份位置與只備份回饋相關資料已由使用者同意。

## 擬採方案與取捨
- 單一 pushes.csv，一列一篇已推送論文，左連接 feedback 與 push_batches。P3 評估只需要「推了哪些、當時候選池多大、使用者怎麼標」，放在同一列最好用；推送篇數每天約 10 篇，檔案一年約數千列。
- 每次整份重寫而不是附加：回饋可以改按，附加會留下過期標籤；整份重寫加固定排序，資料沒變時位元組相同，Git 就不會有差異。
- UTF-8 含 BOM：label_name 是中文，Excel 直接開啟才不會亂碼；GitHub 顯示不受影響。
- Git 操作以 subprocess 呼叫本機 git，只 add pushes.csv，不動資料夾內其他檔案。先比對 git status 決定是否提交；推送每次都做，讓先前失敗的提交自動補上。
- 替代方案：mysqldump 整個資料庫。檔案大、每天整份變動、含不需要的 chat_id 與論文全文，捨棄。
- 未匯出 chat_id、message_id：P3 用不到，chat_id 為個人識別碼。

## 架構與資料影響
新增 arxiv_digest/backup.py（匯出 CSV 與 git 操作）；Store 新增 backup_rows()；config.py 新增 BackupConfig（dir、push 原始字串，resolved() 回傳 (Path, bool)），Config 新增 backup 欄位並有預設值；cli 新增 backup 指令。不變更資料表。config.ini.example 新增 [BACKUP]。

### Check: D1 - Offline isolation
測試禁用 requests 與 pymysql 的真實連線；git 只操作暫存資料夾內的本機 bare repo，不連網路，不讀取 config.ini。

## 驗證與回復
- 新增 tests/test_data_backup.py，涵蓋 R1～R3 與 D1；以 SQLite 替身與暫存 git repo 驗證匯出內容、提交與推送行為、推送失敗後補推及設定驗證。先在未實作的程式上執行確認失敗。
- SQLite 只驗證查詢邏輯，不代表 MySQL 實機驗證；真實 GitHub 推送於交付時以實際執行一次確認。
- 回復：不執行 backup 即無影響；私人 repo 的提交可用 Git 還原。
