# 任務

## 1. 實作與驗證
- [x] 1.1 getUpdates 讀取、依序處理與 offset 確認，回饋寫入與覆蓋；來源 R1；驗證 tests/test_feedback_collect.py
- [x] 1.2 略過非按鈕、他人聊天室、無效資料與對不上推送的點擊；來源 R2；驗證 tests/test_feedback_collect.py
- [x] 1.3 編輯訊息按鈕標示目前選擇，失敗只警告；來源 R3；驗證 tests/test_feedback_collect.py
- [x] 1.4 失敗不確認、重送結果一致、憑證檢查與 token 遮蔽；來源 R4；驗證 tests/test_feedback_collect.py
- [x] 1.5 status 推送與回饋摘要；來源 R5；驗證 tests/test_feedback_collect.py
- [x] 1.6 新測試檔登錄並維持離線隔離；來源 D1；驗證 tests/test_feedback_collect.py
- [x] 1.7 更新 README 的回饋收集與每小時排程說明、feedback 語意；來源 R1；驗證 tests/test_feedback_collect.py
