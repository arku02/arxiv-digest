# 文件同步整理紀錄

日期：2026-09-27 晚間。當天依序封存 fix-announce-lag、add-telegram-push、add-feedback-collect、add-push-translation、fix-translation-simplified 五個變更，並把訂閱分類改為 cs.AI、cs.CL、cs.CV。各變更只更新了自己涉及的段落，本次把其餘過時的說明補齊。純文件整理，未新增產品行為。

## 更新內容

- README.md：開頭介紹改為現況；訂閱範例與每日量改為 3 個分類（2026/09/14–09/20 實測約 263 篇/天，舊的 cs.CV + cs.CL 數據保留為參考）；max_results 與 backfill 建議值依新分類量調整；翻譯耗時改為實測 45～65 秒／篇；排程時間建議 09:30 並說明美國夏令時間的影響，補上筆電用的「不限插電」「錯過補跑」設定；專案結構加入 translator.py；翻譯測試數改為 17 項。
- P3 描述由「LLM 評分」改為「評分（方案待定）」：使用者偏好免費方案，LLM 或本機向量模型尚未決定。涉及 README、config.ini.example、requirements.txt。
- config.ini.example：分類、max_results（3000）、翻譯耗時說明。
- requirements.txt：說明 opencc 為新增套件；移除寫死的 anthropic 註解。
- WORKFLOW-GUIDE.md：測試數 70 項，測試不連線 Ollama。
- arxiv_digest/store.py：模組說明補上 push_batches／pushes（僅註解）。

未修改：docs/MAINTENANCE-2026-09-27.md、.workflow/ 既有紀錄、openspec 規格與封存變更。本機 config.ini 不進版控，已於當天另行改為新分類。

## 本次驗證

- 70 項離線功能測試全數通過，執行案例涵蓋 R1～R9、D1、D2。
- openspec/specs 的 3 份正式規格（fetch-checkpoint、telegram-push、feedback-collect）通過嚴格驗證；沒有進行中的變更。
- 原始結果：[摘要](../.workflow/maintenance/2026-09-27-docs-sync/summary.json)、[離線測試](../.workflow/maintenance/2026-09-27-docs-sync/offline-tests.json)、[測試輸出](../.workflow/maintenance/2026-09-27-docs-sync/offline-tests.log)、[規格檢查](../.workflow/maintenance/2026-09-27-docs-sync/spec-validation.json)。

測試使用模擬回應與記憶體資料庫，不連線 arXiv、MySQL、Telegram 或 Ollama。這份紀錄不是功能變更的交付回條。
