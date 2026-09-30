## ADDED Requirements

### Requirement: R10 - Hold push after failed fetch
非預覽的 push SHALL 在抽樣前讀取最近一筆執行紀錄。狀態為 failed 或 running 時 SHALL 不呼叫 Telegram、不建立批次，記錄說明最近一次抓取未成功並回傳退出碼 1；候選池下界 SHALL 不變，抓取成功後的下一次 push 候選池包含這段期間入庫的論文。沒有執行紀錄或最近一筆為 success 時 SHALL 依 R1 推送。push --dry-run 遇到相同情況 SHALL 只記錄警告並照常預覽。

#### Scenario: Latest fetch failed
- **WHEN** 最近一筆執行紀錄為 failed 時執行 push
- **THEN** 退出碼為 1，沒有 Telegram 請求，push_batches 沒有新增

#### Scenario: Push resumes after recovery
- **WHEN** 上述情況後重新抓取成功，再執行 push
- **THEN** 候選池包含上次成功批次後入庫、尚未推送的論文，依 R1 推送

#### Scenario: Preview still works
- **WHEN** 最近一筆執行紀錄為 failed 時執行 push --dry-run
- **THEN** 印出預覽，退出碼為 0，並記錄警告
