# 模板 0.2.0 工具升級紀錄

日期：2026-09-28。P2 已封存、P3 尚未建立變更，沒有進行中的 OpenSpec 變更，趁此空檔把平面工作流程工具手動更新到公開模板 0.2.0 的路徑隱私版本。模板沒有提供既有平面專案的自動升級，因此逐檔比對後手動套用，未重新導入模板、未改成 `.integration/`。純工具與文件整理，未新增產品行為。

## 比對結果

- 與模板相同、未變動：`openspec/schemas/integrated/`（schema 與五份模板）、`scripts/unittest_runner.py`。
- 升級前的 `scripts/workflow.mjs`、`scripts/run-tests.mjs` 沒有本專案專屬修改，直接換成模板 starter 版本。

## 更新內容

- `scripts/workflow.mjs`、`scripts/run-tests.mjs`：換成新版。新證據先去識別化再計算 `logHash`，原始日誌只留在本機 `.workflow/private/`；有效執行環境（Python、Node）納入證據新鮮度檢查；支援 `workflow.local.json` 與 `WORKFLOW_PYTHON`。
- 新增 `scripts/privacy.mjs`（路徑掃描與 hooks 安裝）、`scripts/doctor.mjs`（環境檢查）及 `docs/PRIVACY.md`（模板原文）。
- `package.json`：加入 `doctor`、`privacy:install`、`privacy:check`、`privacy:history` 指令。
- `workflow.config.json`：`pythonExecutable` 改為可攜的 `python`；本機實際路徑移到不進版控的 `workflow.local.json`。
- `.gitignore`：加入 `workflow.local.json`、`.workflow/private/`、`.workflow/imports/`、`.workflow/python-*.json`。`.gitattributes` 原本的 `.workflow/** -text` 已涵蓋模板要求，未改。
- `PROJECT-RULES.md`：保留本專案說明，Python 路徑說明改為本機檔；補上模板的「歷史證據與隱私」段落。
- `WORKFLOW-GUIDE.md`、`README.md`：Python 設定、doctor、隱私現況與 hooks 狀態。

## 刻意未做

- **未啟用 Git hooks。** 唯讀掃描（`npm run privacy:check`／`privacy:history`）顯示升級前的 18 份紀錄仍含個人路徑：`.workflow/evidence/` 7 份、`.workflow/receipts/` 7 份、`.workflow/maintenance/2026-09-27*/` 4 份；Git 歷史另有舊版 `README.md` 與 `workflow.config.json`。現在啟用會攔下推送。
- **未去識別化舊紀錄。** 需依 PROJECT-RULES「歷史證據與隱私」另行整理並留紀錄。
- **未改寫 Git 歷史或強制推送。** 需另行確認範圍。

## 本次驗證

- `npm run doctor`：ready，Python 3.13.7、OpenSpec 1.13.1、4 個測試檔都存在。
- 70 項離線功能測試全數通過，執行案例涵蓋 R1～R9、D1、D2。
- `openspec/specs` 的 3 份正式規格通過嚴格驗證；沒有進行中的變更。
- 本次紀錄由新版工具輸出並已去識別化：[摘要](../.workflow/maintenance/2026-09-28-template-0.2/summary.json)、[環境檢查](../.workflow/maintenance/2026-09-28-template-0.2/doctor.json)、[離線測試](../.workflow/maintenance/2026-09-28-template-0.2/offline-tests.json)、[測試輸出](../.workflow/maintenance/2026-09-28-template-0.2/offline-tests.log)、[規格檢查](../.workflow/maintenance/2026-09-28-template-0.2/spec-validation.json)。

測試使用模擬回應與記憶體資料庫，不連線 arXiv、MySQL、Telegram 或 Ollama。這份紀錄不是功能變更的交付回條。
