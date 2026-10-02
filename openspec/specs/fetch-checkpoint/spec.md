# fetch-checkpoint Specification

## Purpose
確保每日論文抓取在筆數達到上限時能區分完整結果與尚未完成的區間，保存首次失敗及後續重試的最早起點，讓操作者能依照明確錯誤訊息調整上限並重新執行，而不把未取得的論文當成已處理。

## Requirements

### Requirement: R1 - Complete fetch
系統 SHALL 在有效設定下，保留未達上限的分頁抓取、空結果成功與既有去重行為。空時間區間 SHALL 不發送請求。

#### Scenario: Complete fetch acceptance
- **WHEN** 取回筆數未達 max_results 或沒有結果
- **THEN** 完整結果交由既有儲存流程處理，成功起點推進至區間終點

### Requirement: R2 - Detect incomplete window
系統 SHALL 在取回 max_results 筆後，以相同查詢在下一個 offset 探查最多一筆。若探查為空 SHALL 視為完整；若仍有論文或探查失敗 SHALL 失敗且不儲存這批部分結果，不標記該區間 success。page_size 或 max_results 非正整數 SHALL 在請求前拒絕。上限限制交付資料筆數，探查額外最多取得一筆，不入庫。

#### Scenario: Detect incomplete window acceptance
- **WHEN** 完整上限批次後的探查仍有一筆
- **THEN** 這次執行失敗，原成功起點保留；空探查則允許完成

### Requirement: R3 - Preserve retry start
daily SHALL 從「最新成功終點往前 lookback_days 天」與尚未被後續成功區間完整覆蓋之 failed/running 區間起點中選最早值。failed/running 區間起點 SHALL 直接沿用，不再往前加 lookback_days。兩者皆不存在才使用 initial_backfill_days，首次回溯不另加 lookback_days。成功覆蓋 SHALL 具有較大的執行 id，且起點不晚於失敗起點、終點不早於失敗終點。首次失敗、未完成執行及較早 backfill 失敗 SHALL 可重新抓取；重試與回看的重複資料沿用 arxiv_id 去重。

#### Scenario: Preserve retry start acceptance
- **WHEN** 第一次執行未完成，隔日提高上限後重跑
- **THEN** 沿用先前保存起點，成功涵蓋後才向前推進

#### Scenario: Repeated failures keep the same start
- **WHEN** 已有成功紀錄後，連續兩次 daily 都未完成，第三次才成功
- **THEN** 三次執行的查詢起點相同，都是該成功終點往前 lookback_days 天

### Requirement: R4 - Actionable failure
未完成的 daily 指令 SHALL 回傳非零退出碼。錯誤 SHALL 說明起點保留、調高 max_results 後重跑、此次未完成查詢的起迄 UTC 時間（分鐘精度），以及系統不會自動調高上限。不得把上限中止描述為完整成功。

#### Scenario: Actionable failure acceptance
- **WHEN** 抓取超過上限
- **THEN** 退出碼為 1 且錯誤包含起點保留及重跑方法

#### Scenario: Operator can identify retry window
- **WHEN** 2026-09-01 00:00 至 2026-09-02 00:00 UTC 的查詢超過上限
- **THEN** 退出碼為 1，錯誤顯示上述 UTC 起訖時間、保留起點及調高 max_results 後重跑，並說明不會自動調高上限

### Requirement: R5 - Announcement lag lookback
arXiv API 在論文公告前查不到該論文。daily SHALL 依 R3 每次重新查詢最新成功終點前 lookback_days 天，使前次執行時尚未公告的論文在公告後的下一次 daily 入庫。lookback_days SHALL 預設為 4；設為 0 時起點與未回看時相同。lookback_days 不是非負整數時 SHALL 在連線資料庫與發送請求前拒絕。回看取回的既有論文 SHALL 以 arxiv_id 去重，新增筆數只計入新論文。backfill 指定天數時 SHALL 以指定起點查詢，不另加 lookback_days。

#### Scenario: Paper announced after an earlier run
- **WHEN** 週五提交的論文在週六、週日 daily 執行時尚未公告，週一公告後再執行 daily
- **THEN** 週一的查詢區間包含該論文提交時間，論文入庫

#### Scenario: Lookback disabled
- **WHEN** lookback_days 為 0，其餘條件同上
- **THEN** 查詢起點等於最新成功終點，週一執行不包含該論文

#### Scenario: Overlap is deduplicated
- **WHEN** 回看區間內的論文已在前一次 daily 入庫
- **THEN** 這些論文不重複入庫，新增筆數只計新論文

#### Scenario: Invalid lookback rejected
- **WHEN** lookback_days 為負數或非整數
- **THEN** 讀取設定即失敗，daily 回傳非零退出碼，不連線資料庫、不發送請求

#### Scenario: Backfill keeps explicit start
- **WHEN** 執行 backfill --days 7
- **THEN** 查詢起點為執行時間往前 7 天，不另加 lookback_days

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
daily 失敗時 SHALL 以設定的 Telegram chat 發送一則不含按鈕的 HTML 通知，內容 SHALL 說明今天暫不推送、失敗原因（經 HTML 跳脫、遮蔽 bot token、最多 300 字）與後續處理：上限錯誤時提示調高 max_results 後重跑且不會自動重試；其他錯誤在 R8 啟用時說明每天 start_hour～end_hour 每小時自動重試、成功後補推，未啟用時提示手動重跑 daily 與 push。前一筆執行紀錄也是 failed，且與本次同為上限錯誤或同為非上限錯誤時，SHALL 不再通知，使同一段同類型的連續失敗只通知一次；兩者類型不同時 SHALL 照常通知。Telegram 未設定、設定為範例值或發送失敗時 SHALL 只記錄，不改變 daily 的退出碼（仍為 1）與 runs 紀錄。

#### Scenario: First failure notifies
- **WHEN** 上一次執行成功，這次 daily 因 HTTP 429 失敗
- **THEN** 退出碼為 1，Telegram 收到一則沒有按鈕、含 HTTP 429 與重試時段的通知

#### Scenario: Consecutive failure is silent
- **WHEN** 上一次執行已是 failed（HTTP 429），這次 daily 又因 HTTP 429 失敗
- **THEN** 退出碼為 1，沒有 Telegram 請求

#### Scenario: Limit failure needs operator
- **WHEN** daily 因超過 max_results 失敗
- **THEN** 通知提示調高 max_results，並說明不會自動重試

#### Scenario: Failure kind change notifies
- **WHEN** 上一次執行因 HTTP 429 失敗，這次因超過 max_results 失敗；或上一次因超過 max_results 失敗，這次因 HTTP 429 失敗
- **THEN** 退出碼為 1，Telegram 收到一則依本次錯誤類型說明後續處理的通知

#### Scenario: Consecutive limit failure is silent
- **WHEN** 上一次與這次 daily 都因超過 max_results 失敗
- **THEN** 退出碼為 1，沒有 Telegram 請求

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
