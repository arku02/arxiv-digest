# 審查

```json
{
  "mode": "full",
  "decision": "ready",
  "reviewer": "Claude Opus 5.5：程式與規格交叉審查",
  "rationale": "已核對 R6 只對 429／503 改用 Retry-After 或 60、120 秒，其他錯誤維持 request_delay 退避，最後一次失敗不再等待；R7 通知在憑證無效或發送失敗時只記錄，daily 退出碼與 runs 紀錄不變，連續失敗以前一筆 runs 狀態判斷只通知一次；R10 在建立批次前檢查，不改 R1 的候選池下界；R8 在 collect 的 finally 中執行且自行捕捉例外，不蓋掉收集錯誤，時段與設定檢查在連線資料庫前完成，上限錯誤與剛開始的 running 不重抓。為符合 feedback-collect R4，collect 先驗證 Telegram 憑證。補抓時段 10:00～22:00 與「不新增排程」為使用者 2026-09-30 同意的方案。不聲稱 MySQL 實機或真實 arXiv 429 驗證。",
  "openQuestions": [],
  "coverage": [
    { "requirement": "R6", "task": "1.1", "test": "tests/test_fetch_recovery.py" },
    { "requirement": "R7", "task": "1.2", "test": "tests/test_fetch_recovery.py" },
    { "requirement": "R8", "task": "1.3", "test": "tests/test_fetch_recovery.py" },
    { "requirement": "R10", "task": "1.4", "test": "tests/test_fetch_recovery.py" },
    { "requirement": "D1", "task": "1.5", "test": "tests/test_fetch_recovery.py" },
    { "requirement": "R8", "task": "1.6", "test": "tests/test_fetch_recovery.py" }
  ]
}
```

## 檢查內容
- 需求來源：proposal.md 引用 2026-09-30 本機 runs／push_batches 查詢結果；429 的冷卻時間為推論，已標示。
- 規格與程式：R6 對應 fetcher._request 與 _retry_after；R7 對應 cli.notify_fetch_failure 與 cmd_daily；R8 對應 cli.run_catch_up、_needs_retry、cmd_collect 及 config.RetryConfig；R10 對應 run_push 建立批次前的檢查；TelegramClient.send 的 reply_markup 改為選用。
- 測試：R6 以假時鐘與記錄 sleep 參數驗證等待秒數；R7 驗證首次通知內容、連續失敗不通知、上限錯誤提示、停用補抓時的提示、Telegram 未設定或連線失敗；R8 驗證補抓成功推送、回饋失敗仍補抓、補抓再失敗不通知、時段外、無需補抓、逾時 running、設定錯誤與讀檔預設值；R10 驗證 failed／running 暫停、恢復後推送、預覽照常；D1 確認沒有真實 HTTP 或 MySQL 連線。
- 既有測試斷言未修改。測試替身調整兩處：test_telegram_push 的 SQLite schema 加入 runs 表並解析 window_start／window_end；test_feedback_collect 的 runs 建表改為 IF NOT EXISTS。
- 不需新增 ADR；取捨與已知限制記錄於 design.md。

## 執行順序說明
實作前先執行新測試：既有 70 項（含替身調整）通過，新測試檔因 RetryConfig 不存在而匯入失敗。實作後第一次執行有 1 項失敗，原因是測試的假時鐘從 0 起算觸發了節流等待，屬測試替身問題，修正假時鐘後通過；另發現 collect 在憑證錯誤時仍連線資料庫，違反 feedback-collect R4，已改程式修正。此過程未經 workflow 保存；正式證據以 verify 產生者為準。

## 實際驗證
由 verify 產生，見 .workflow/evidence/add-fetch-failure-guard.json 與 .log。
