# 任務

## 1. 實作與驗證
- [x] 1.1 429／503 依 Retry-After 或 60、120 秒等待，最後一次失敗不等待；來源 R6；驗證 tests/test_fetch_recovery.py
- [x] 1.2 daily 失敗時發送 Telegram 通知，連續失敗只通知一次，通知失敗不影響結果；來源 R7；驗證 tests/test_fetch_recovery.py
- [x] 1.3 collect 後依 [RETRY] 設定與最近執行紀錄補抓並推送，新增設定驗證；來源 R8；驗證 tests/test_fetch_recovery.py
- [x] 1.4 push 在最近一次抓取 failed／running 時暫停，預覽只警告；來源 R10；驗證 tests/test_fetch_recovery.py
- [x] 1.5 新增測試維持離線隔離並登錄 workflow.config.json，既有測試替身加入 runs 表；來源 D1；驗證 tests/test_fetch_recovery.py
- [x] 1.6 更新 config.ini.example 與 README 的失敗處理、補抓時段與紀錄檔說明；來源 R8；驗證 tests/test_fetch_recovery.py
