## Purpose
把使用者在 Telegram 按下的回饋與對應的推送紀錄，定期匯出成可閱讀的 CSV 並提交到私人 git repo，讓無法重建的標註資料在本機資料庫遺失時仍可取回。

## ADDED Requirements

### Requirement: R1 - Export push and feedback records
backup SHALL 把每一筆推送紀錄匯出成備份資料夾內的 pushes.csv（UTF-8 含 BOM），欄位依序為 arxiv_id、title、categories、published、batch_id、pool_size、batch_sent、pushed_at、label、label_name、feedback_at。label 為 0、1、2，label_name 分別為 沒興趣、有興趣、超想讀；沒有回饋時兩欄與 feedback_at 皆為空字串。列 SHALL 依 pushed_at、arxiv_id 排序，時間格式為 YYYY-MM-DD HH:MM:SS。檔案 SHALL 不含 chat_id 與 message_id。資料未變時重新匯出 SHALL 產生位元組相同的檔案。

#### Scenario: Export with and without feedback
- **WHEN** 已推送 3 篇，其中 1 篇回饋 ⭐、1 篇回饋 👎
- **THEN** pushes.csv 有表頭與 3 列，兩篇的 label／label_name 為 2／超想讀與 0／沒興趣，第三篇三個回饋欄位為空，檔案中沒有 chat_id 或 message_id 的值

#### Scenario: Stable output
- **WHEN** 資料未變時連續執行兩次 backup
- **THEN** 兩次的 pushes.csv 位元組相同

### Requirement: R2 - Commit and push changes
備份資料夾 SHALL 是既有的 git 工作目錄；資料夾不存在或不是 git 工作目錄時，backup SHALL 在連線資料庫前失敗並指出路徑。pushes.csv 內容與已提交版本不同時，backup SHALL 只提交該檔案，提交訊息包含推送篇數與回饋篇數；相同時 SHALL 不建立提交。[BACKUP] push 啟用時，backup SHALL 每次執行 git push，使先前推送失敗的提交補上；git push 失敗時 SHALL 回傳非零退出碼並保留本機提交。

#### Scenario: New feedback committed
- **WHEN** 上次備份後新增一筆回饋，執行 backup
- **THEN** 遠端多一個提交，內容為更新後的 pushes.csv

#### Scenario: No change no commit
- **WHEN** 上次備份後資料沒有變動，執行 backup
- **THEN** 不建立新提交，退出碼為 0

#### Scenario: Push failure recovered later
- **WHEN** 有變動但 git push 失敗，之後遠端恢復且資料不再變動，再執行 backup
- **THEN** 第一次退出碼為 1 且本機保留提交；第二次不建立新提交，但遠端取得先前的提交

#### Scenario: Not a git repository
- **WHEN** 備份資料夾不存在或沒有 .git
- **THEN** 退出碼為 1，錯誤指出該路徑，未連線資料庫

### Requirement: R3 - Backup settings
[BACKUP] 區段 SHALL 為選用。dir 預設為專案根目錄上一層的 arxiv-digest-data；相對路徑以專案根目錄為基準。push 預設 true；不是可辨識的布林值時 backup SHALL 在連線資料庫前失敗並指出設定名稱。push 為 false 時 SHALL 只提交不推送。[BACKUP] 設定錯誤 SHALL 不影響 daily、push、collect 與 status。

#### Scenario: Defaults
- **WHEN** config.ini 沒有 [BACKUP] 區段
- **THEN** 備份資料夾為專案根目錄旁的 arxiv-digest-data，push 為 true

#### Scenario: Commit only
- **WHEN** push 為 false 且資料有變動
- **THEN** 建立本機提交，不執行 git push

#### Scenario: Invalid push flag
- **WHEN** push 為 maybe
- **THEN** backup 退出碼為 1、錯誤指出 push 且未連線資料庫；daily 照常執行
