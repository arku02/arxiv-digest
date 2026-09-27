# 審查

```json
{
  "mode": "full",
  "decision": "ready",
  "reviewer": "Claude Opus 5.5：規格、設計與測試交叉審查",
  "rationale": "已核對 R1 以 getUpdates offset 在處理成功後才確認、失敗時整批重送，搭配 SELECT 後 INSERT/UPDATE 的寫入可重複執行；R2 以設定 chat_id 與 pushes 的 (chat_id, message_id) 對應防止誤寫，略過項也確認以免阻塞；R3 按鈕編輯屬顯示用途，失敗不影響資料；R4 憑證檢查沿用 push 且不受 daily_limit 影響；R5 無推送時避免除以零。不呼叫 answerCallbackQuery 的取捨與每小時排程一致。每項需求與任務都有 test_R*/test_D1_ 案例。無待決問題；不聲稱 MySQL 或真實 Telegram 已驗證。",
  "openQuestions": [],
  "coverage": [
    { "requirement": "R1", "task": "1.1", "test": "tests/test_feedback_collect.py" },
    { "requirement": "R2", "task": "1.2", "test": "tests/test_feedback_collect.py" },
    { "requirement": "R3", "task": "1.3", "test": "tests/test_feedback_collect.py" },
    { "requirement": "R4", "task": "1.4", "test": "tests/test_feedback_collect.py" },
    { "requirement": "R5", "task": "1.5", "test": "tests/test_feedback_collect.py" },
    { "requirement": "D1", "task": "1.6", "test": "tests/test_feedback_collect.py" },
    { "requirement": "R1", "task": "1.7", "test": "tests/test_feedback_collect.py" }
  ]
}
```

## 檢查內容
- 需求來源：proposal 引用使用者 2026-09-27 的三級語意與每小時收集決定；不即時回應按鈕與不保存變更歷史列為非目標。
- 設計列出 pymysql UPDATE 影響列數與 Telegram offset 確認語意等已知事實，並說明不自存 offset 的理由。
- 測試以 SQLite 執行 Store 實際 SQL，以模擬 getUpdates 佇列驗證 offset 確認與重送；D1 確認新測試檔已登錄且未實際連線。
- 不需 ADR；取捨記錄於 design.md。
- 手動實機確認（非自動測試）：2026-09-27 使用者在 3 則推送訊息按下按鈕，其中 1 則改按；collect 記錄 4 筆點擊、略過 0 筆，feedback 為 3 筆（⭐、👎、⭐），status 顯示推送 10 篇、回饋 3 篇、回饋率 30%，使用者確認手機上的 ✅ 標示正確。使用者先前傳給 bot 的 /start 未出現在 getUpdates 結果中，因此沒有略過項可實機觀察，略過邏輯僅由離線測試涵蓋。

## 實際驗證
由 verify 產生，見 .workflow/evidence/add-feedback-collect.json 與 .log。
