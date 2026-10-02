## MODIFIED Requirements

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
