# 審查

```json
{
  "mode": "lite",
  "decision": "ready",
  "reviewer": "Claude Opus 5.5：程式與規格交叉審查",
  "rationale": "已核對 R3 修改只對成功終點回看、失敗起點沿用，避免連續失敗漂移；成功覆蓋判定不變，重試起點仍不晚於失敗起點。R5 的預設值、0、非法值、重疊去重與 backfill 不回看皆有對應測試。預設 4 天依公告時程推論，假日停刊與既有缺口列為非目標並於 README 說明補抓方式。不聲稱即時 API 或 MySQL 實機驗證。",
  "openQuestions": [],
  "coverage": [
    { "requirement": "R3", "task": "1.1", "test": "tests/test_fetch_checkpoint.py" },
    { "requirement": "R5", "task": "1.2", "test": "tests/test_fetch_checkpoint.py" },
    { "requirement": "D1", "task": "1.3", "test": "tests/test_fetch_checkpoint.py" },
    { "requirement": "R5", "task": "1.4", "test": "tests/test_fetch_checkpoint.py" }
  ]
}
```

## 檢查內容
- 需求來源：proposal.md 引用 2026-09-27 本機 runs／papers 查詢結果；公告延遲為推論，已標示。
- 規格與程式：R3 對應 Store.next_fetch_start(lookback)；R5 對應 ArxivConfig.lookback_days 驗證、load_config 讀取及 cli.run_fetch 套用；backfill 路徑未改。
- 測試：R3 連續失敗起點不變；R5 以模擬 API 依「現在時間」決定可見性，重現週五提交、週一公告；lookback_days=0 為對照組；D1 確認新情境未呼叫 requests／pymysql。
- 既有測試斷言未修改。測試替身調整三處：MemoryStore.next_fetch_start 轉傳參數、新增 seed_success 讓預置紀錄與 run id 對齊、run_job 可注入 session。
- 不需新增 ADR；取捨記錄於 design.md。

## 執行順序說明
實作前先以未修正程式執行新測試：舊 14 項通過，新增 8 項失敗；核心情境新增筆數為 [0, 0, 0, 1]，週五論文漏抓，與正式資料庫症狀一致。此紅燈執行在 check 之前完成，未經 workflow 保存；正式證據以 verify 產生者為準。

## 實際驗證
由 verify 產生，見 .workflow/evidence/fix-announce-lag.json 與 .log。
