## ADDED Requirements

### Requirement: R6 - Rate limit wait
每次 arXiv API 請求 SHALL 最多嘗試 3 次。回應為 HTTP 429 或 503 時，下一次嘗試前 SHALL 等待 Retry-After 標頭的秒數（非負整數，超過 300 時以 300 計）；沒有或無法解析時，第 1、2 次失敗後分別等待 60 與 120 秒。其他失敗 SHALL 維持 request_delay × 2^(n−1) 秒。第 3 次失敗後 SHALL 不再等待，直接依既有規則讓本次執行失敗並保留續抓起點。

#### Scenario: Retry-After honored
- **WHEN** 第一次請求回應 429 且 Retry-After 為 30，第二次回應 200
- **THEN** 只等待 30 秒一次，本次抓取成功

#### Scenario: Default rate limit backoff
- **WHEN** 前兩次請求回應 429 且沒有 Retry-After，第三次回應 200
- **THEN** 依序等待 60 與 120 秒，本次抓取成功

#### Scenario: Persistent rate limit
- **WHEN** 三次請求都回應 429 且沒有 Retry-After
- **THEN** 只等待 60 與 120 秒，本次執行記為 failed，錯誤包含 HTTP 429

### Requirement: R7 - Fetch failure notification
daily 失敗時 SHALL 以設定的 Telegram chat 發送一則不含按鈕的 HTML 通知，內容 SHALL 說明今天暫不推送、失敗原因（經 HTML 跳脫、遮蔽 bot token、最多 300 字）與後續處理：上限錯誤時提示調高 max_results 後重跑且不會自動重試；其他錯誤在 R8 啟用時說明每天 start_hour～end_hour 每小時自動重試、成功後補推，未啟用時提示手動重跑 daily 與 push。前一筆執行紀錄也是 failed 時 SHALL 不再通知，使同一段連續失敗只通知一次。Telegram 未設定、設定為範例值或發送失敗時 SHALL 只記錄，不改變 daily 的退出碼（仍為 1）與 runs 紀錄。

#### Scenario: First failure notifies
- **WHEN** 上一次執行成功，這次 daily 因 HTTP 429 失敗
- **THEN** 退出碼為 1，Telegram 收到一則沒有按鈕、含 HTTP 429 與重試時段的通知

#### Scenario: Consecutive failure is silent
- **WHEN** 上一次執行已是 failed，這次 daily 又失敗
- **THEN** 退出碼為 1，沒有 Telegram 請求

#### Scenario: Limit failure needs operator
- **WHEN** daily 因超過 max_results 失敗
- **THEN** 通知提示調高 max_results，並說明不會自動重試

#### Scenario: Telegram unavailable
- **WHEN** Telegram 未設定或 sendMessage 連線失敗時 daily 失敗
- **THEN** 退出碼仍為 1，runs 記為 failed，記錄中沒有 bot token

### Requirement: R8 - Hourly catch-up
collect 處理完回饋後（包含回饋處理失敗時）SHALL 檢查是否補抓：[RETRY] 啟用、本機時間的小時數在 [start_hour, end_hour) 內，且最近一筆執行紀錄為非上限錯誤的 failed，或為開始超過 60 分鐘的 running。符合時 SHALL 依 R3 執行 daily 抓取；成功後 SHALL 執行 push，失敗時依 R7 處理並使 collect 退出碼為 1。不符合時 SHALL 不發送任何 arXiv 請求、不推送。[RETRY] 區段 SHALL 為選用，預設 enabled=true、start_hour=10、end_hour=22；enabled 不是可辨識的布林值、小時不是 0～24 的整數或 start_hour 不小於 end_hour 時，補抓 SHALL 不執行並記錄指出設定名稱的錯誤，collect 退出碼為 1，回饋收集不受影響。[RETRY] 設定錯誤 SHALL 不影響 daily、backfill、push 與 status。

#### Scenario: Retry succeeds and pushes
- **WHEN** 最近一次執行 failed（HTTP 429），11:00 執行 collect，arXiv 已恢復
- **THEN** 回饋照常收集，重新抓取成功並推送候選論文，collect 退出碼為 0

#### Scenario: Retry fails again
- **WHEN** 最近一次執行 failed，collect 補抓時 arXiv 仍回應 429
- **THEN** 不推送、沒有新的通知，collect 退出碼為 1，下一小時會再試

#### Scenario: Outside retry hours
- **WHEN** 最近一次執行 failed，23:00 執行 collect
- **THEN** 不發送 arXiv 請求，collect 退出碼為 0

#### Scenario: Nothing to retry
- **WHEN** 最近一次執行 success、為上限錯誤的 failed，或為 10 分鐘前開始的 running
- **THEN** 不發送 arXiv 請求，collect 退出碼為 0

#### Scenario: Stale running retried
- **WHEN** 最近一次執行為 90 分鐘前開始、仍是 running
- **THEN** 重新抓取

#### Scenario: Invalid retry settings
- **WHEN** [RETRY] start_hour 為 22、end_hour 為 10
- **THEN** 回饋照常收集，不補抓，collect 退出碼為 1 且錯誤指出 start_hour；daily 照常執行
