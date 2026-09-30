# 技術設計

## 已知事實
- 基準規格：openspec/specs/fetch-checkpoint/spec.md（R1～R5）與 openspec/specs/telegram-push/spec.md（R1～R9）。
- ArxivFetcher._request 最多嘗試 3 次，每次失敗後等待 request_delay × 2ⁿ（預設 3、6、12 秒），第 3 次失敗後仍會等待；非 200 回應一律轉成 RuntimeError("HTTP <code>")。
- cli.run_fetch 失敗時把 runs 標為 failed（錯誤前 500 字）後重新拋出；cli.main 捕捉並回傳 1。上限錯誤 FetchLimitExceeded 的訊息以「已達單次上限」開頭。
- cli.run_push 以 last_success_push_start 為候選池下界；候選池為空時仍建立 success 批次。它不讀取 runs。
- cli.run_collect 只處理 getUpdates；Windows 排程每小時執行一次 collect，每天 09:30 依序執行 daily、push。
- Store.recent_runs(limit) 已提供 id、started_at、status、error 等欄位，依 id 由新到舊。runs.started_at 為資料庫時鐘。
- TelegramClient.send 必須帶 reply_markup；錯誤訊息已遮蔽 token。
- 2026-09-30 的事件經過見 proposal.md。

## 假設與待決問題
- 假設 arXiv 的 429 多為短時間限流，等 1～2 分鐘或下一小時即可恢復；此為推論，未取得 arXiv 官方的冷卻時間。
- 假設 09:30 的 daily 通常在幾分鐘內結束；最近一筆 running 開始不到 60 分鐘時視為仍在執行，不重複抓取。
- 補抓時段預設 10:00～22:00（本機時間），使用者已同意；10:00 起算是為了避開 09:30 的 daily，避免同一早上推兩批。
- 無待決業務問題。

## 擬採方案與取捨
- 限流等待（R6）：_request 對 429／503 讀 Retry-After（整數秒、上限 300），否則等 60 × 2^(n−1)。最後一次失敗不再等待。最壞情況單一請求多等約 3 分鐘，不需調整排程逾時。
- 失敗通知（R7）：cmd_daily 包住 run_fetch，失敗時先檢查 Telegram 設定，未設定就只記錄；已設定才開資料庫讀 recent_runs(2)，前一筆為 failed 就不發送。整個通知包在 try 裡，任何錯誤只記警告，再把原本的例外往外拋，退出碼與 runs 紀錄不變。backfill 失敗不通知（操作者手動執行，當下就看得到）。
- 暫停推送（R10）：run_push 在建立批次前讀 recent_runs(1)；failed／running 時拋出 FetchNotReady。不建批次，所以候選池下界不動，不必改 R1 的下界邏輯。
- 每小時補抓（R8）：cmd_collect 以 try/finally 在 run_collect 之後呼叫 run_catch_up；run_catch_up 自己捕捉所有例外並回傳是否成功，避免蓋掉 collect 本身的例外。判斷順序：設定 → 本機時段 → 最近一筆執行，前兩項不通過時不連線資料庫。補抓失敗時呼叫同一個通知函式，由 R7 的連續失敗規則避免洗版。
- 上限錯誤判斷：runs.error 以 fetcher 的 LIMIT_ERROR_PREFIX（「已達單次上限」）開頭時不補抓；常數同時用在 FetchLimitExceeded 的訊息，兩處不會各自漂移。
- 替代方案：新增獨立的每小時排程或在 daily 內部迴圈等待。前者需要系統管理員修改排程，後者會讓 daily 長時間佔住並延後 push；兩者都捨棄。
- 取捨：collect 的職責擴大為「收回饋＋補抓」。以 [RETRY] enabled=false 可完全關閉補抓。
- collect 先檢查 Telegram 憑證再進入 try/finally：feedback-collect R4 要求憑證錯誤在連線資料庫前失敗，補抓推送也需要同一組憑證，憑證錯誤時兩者都不做。
- 已知限制：runs 不區分 daily 與 backfill，手動 backfill 失敗也會讓 push 暫停，直到下一次抓取成功；抓取在寫入 runs 之前就失敗（例如資料庫連不上）時，通知判斷的「前一筆」會是更早的紀錄，可能多通知一次或少通知一次。

## 架構與資料影響
不變更資料表。config.py 新增 RetryConfig（原始字串，validated() 回傳 None 或 (start_hour, end_hour)），Config 新增 retry 欄位並有預設值，既有建構方式不受影響。TelegramClient.send 的 reply_markup 改為選用。cli 新增 localnow() 以便測試固定本機時間。config.ini.example 新增 [RETRY]；未設定時採預設值。

### Check: D1 - Offline isolation
新增測試禁用 requests 與 pymysql 的真實連線，以模擬 arXiv 回應、模擬 Bot API、SQLite 及 patch 過的 sleep／時間執行，不讀取 config.ini。

## 驗證與回復
- 新增 tests/test_fetch_recovery.py，涵蓋 R6、R7、R8、R10、D1；先在未修改程式上執行確認失敗，再實作。
- 既有測試替身加入 runs 表（test_telegram_push 的 SQLite schema；test_feedback_collect 改為 IF NOT EXISTS），不修改既有斷言。
- SQLite 只驗證查詢邏輯，不代表 MySQL 實機驗證；實際 arXiv 429 行為未以即時 API 重現。
- 回復：在 config.ini 設 [RETRY] enabled = false 可停用補抓；還原程式即恢復原行為，資料表不需遷移。
