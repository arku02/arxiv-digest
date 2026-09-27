# 審查

```json
{
  "mode": "lite",
  "decision": "ready",
  "reviewer": "Codex：程式與規格交叉審查",
  "rationale": "已核對完整抓取、額外探查、首次失敗起點和成功覆蓋判定。接受保守重試需手動提高上限的取捨，不聲稱自動追平或正式 MySQL 驗證。",
  "openQuestions": [],
  "coverage": [
    {
      "requirement": "R1",
      "task": "1.1",
      "test": "tests/test_fetch_checkpoint.py"
    },
    {
      "requirement": "R2",
      "task": "1.2",
      "test": "tests/test_fetch_checkpoint.py"
    },
    {
      "requirement": "R3",
      "task": "1.3",
      "test": "tests/test_fetch_checkpoint.py"
    },
    {
      "requirement": "R4",
      "task": "1.4",
      "test": "tests/test_fetch_checkpoint.py"
    }
  ]
}
```

實際執行證據由 verify 產生。讀取程式確認問題後，以未修正版執行同一套測試保存失敗紀錄。
