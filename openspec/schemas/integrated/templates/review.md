# 審查紀錄

## 結構化審查
下列 JSON 由審查者維護，不含第二份任務進度。pending 不能進入實作；
確認規格、設計與任務一致後才改成 ready，並填寫具體 rationale。
```json
{
  "mode": "full",
  "decision": "pending",
  "reviewer": "",
  "rationale": "",
  "openQuestions": [],
  "coverage": [
    { "requirement": "R1", "task": "1.1", "test": "test/example.test.mjs" }
  ]
}
```

## 檢查內容
- 需求與上游產品來源一致嗎？
- 範圍、角色、邊界、非功能要求是否可驗證？
- 設計是否區分現況、假設與計畫？
- 每項需求／技術檢查和任務是否都有測試對應？
- 測試名稱是否以對應的 R1: 或 D1: 開頭，且斷言真正涵蓋需求？
- 是否需要回寫架構或新增 ADR？

## 實際驗證
尚未執行。執行 verify 後讀取 .workflow/evidence/<change>.json 與對應測試輸出。
不要複製另一份通過狀態；證據變動或過期時以工具最新檢查為準。
