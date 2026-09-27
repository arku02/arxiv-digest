# 審查

```json
{
  "mode": "lite",
  "decision": "ready",
  "reviewer": "Claude Opus 5.5：規格、設計與測試交叉審查",
  "rationale": "已依 44 段實際翻譯比對 OpenCC 各模式，確認直接套用會誤改正確繁體字，改採只轉換 Big5 常用字以外字元的做法，並以測試保證常用字零改動。用語對照只收錄無歧義詞，算法以負向回顧避免重複替換。不處理本身是常用字的簡體字與誤譯，已列為非目標。R9 與 D2 均有對應任務與測試；無待決問題。",
  "openQuestions": [],
  "coverage": [
    { "requirement": "R9", "task": "1.1", "test": "tests/test_push_translation.py" },
    { "requirement": "D2", "task": "1.2", "test": "tests/test_push_translation.py" },
    { "requirement": "R9", "task": "1.3", "test": "tests/test_push_translation.py" }
  ]
}
```

## 檢查內容
- 需求來源：add-push-translation 實機預覽出現的簡體字與大陸用語；使用者要求修正簡體字並同意安裝 opencc。
- 設計記錄 OpenCC 各模式實測誤改與 Big5 常用字區段等事實，說明無法修正「后」「干」等字的取捨。
- 測試在既有已登錄的 tests/test_push_translation.py 新增 test_R9_ 與 test_D2_ 案例，沿用模擬 Ollama 與離線隔離。
- 不需 ADR。
- 手動實機確認（非自動測試）：2026-09-27 push --dry-run 候選為 0 篇（當晚已推送，尚無新論文），無法用來確認；改以 OllamaTranslator 直接翻譯 5 篇（含前次預覽出現「该」「情况」的 2609.27452、2609.30214 與先前試翻 3 篇），每篇 45～66 秒，結果無任何非常用字，剩「優化」1 處（依設計保留）。模型輸出每次不同，無法確認本次原始輸出是否含簡體字；修正效果另以前次預覽的實際輸出重跑 to_taiwan 確認（「该→該」「况→況」各 1 處，其餘不變）。

## 實際驗證
由 verify 產生，見 .workflow/evidence/fix-translation-simplified.json 與 .log。
