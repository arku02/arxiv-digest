# 審查

```json
{
  "mode": "lite",
  "decision": "ready",
  "reviewer": "Claude Opus 5.5：程式與規格交叉審查",
  "rationale": "R7 只改連續失敗的靜默條件：前一筆 failed 且與本次同為上限或同為非上限錯誤才不通知。類型判斷抽成 cli._is_limit_error，_needs_retry 改用同一函式，R8 補抓條件不變。通知內容、Telegram 不可用時的處理、退出碼與 runs 紀錄不變。原 Consecutive failure is silent 情境限定為同類型（429→429），語意與舊測試一致。事件依據為 2026-10-03 查本機 runs 與 logs。不聲稱 MySQL 實機或真實 Telegram 驗證。",
  "openQuestions": [],
  "coverage": [
    { "requirement": "R7", "task": "1.1", "test": "tests/test_fetch_recovery.py" }
  ]
}
```

## 檢查內容
- 需求來源：proposal.md 引用 2026-10-02 第 27、28 次 runs 與 logs/collect.log 的「不重複通知」紀錄。
- 規格與程式：R7 對應 cli.notify_fetch_failure 與 _is_limit_error；_needs_retry 改用 _is_limit_error，行為不變。
- 測試：新增 test_R7_failure_kind_change_notifies（429→上限、上限→429 皆通知，並核對各自的後續處理文字）與 test_R7_consecutive_limit_failure_is_silent；既有 test_R7_consecutive_failure_is_silent（429→429）保留。
- 既有測試斷言未修改。不需新增 ADR。

## 執行順序說明
實作前先執行新測試：test_R7_failure_kind_change_notifies 因沒有發出通知而失敗（重現事件），上限→上限案例原本即通過。實作後 tests/test_fetch_recovery.py 23 項與 npm test 104 項通過。此過程未經 workflow 保存；正式證據以 verify 產生者為準。

## 實際驗證
由 verify 產生，見 .workflow/evidence/fix-limit-notice.json 與 .log。
