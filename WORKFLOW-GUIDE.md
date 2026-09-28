# arXiv Digest 開發與驗證手冊

本專案已接入第一版模板的平面工作流程，工具位於 `scripts/`，規格由 OpenSpec 1.13.1 管理。沿用此入口即可，不需要重新導入模板或改成 `.integration/`。

## 1. 準備環境

日常抓取使用 Python 與 MySQL；離線驗證使用 Python 套件、Node.js 20.19 以上及本地 OpenSpec 工具。在專案根目錄安裝：

```text
python -m pip install -r requirements.txt
npm ci --ignore-scripts --no-audit --no-fund
```

`workflow.config.json` 已登錄 `tests/test_fetch_checkpoint.py`、`tests/test_telegram_push.py`、`tests/test_feedback_collect.py` 與 `tests/test_push_translation.py`，不必替換成範例測試路徑。`pythonExecutable` 必須指向已安裝專案套件的 Python；移機或切換虛擬環境時才調整。

本手冊不會自動建立或修改 Windows 排程，日常使用及設定方式見 [README](README.md)。

## 2. 先跑既有離線測試

```text
npm test
```

目前有 70 項功能測試，涵蓋完整抓取、達到上限、保留續抓起點、錯誤提示、公告延遲回看、Telegram 推送、回饋收集、中文翻譯及簡體字修正。測試使用模擬 Atom 回應、模擬 Bot API、模擬 Ollama、固定時間及記憶體資料庫，不讀取 `config.ini`，不連線 arXiv、MySQL、Telegram 或 Ollama。

SQLite 只驗證查詢邏輯，不代表真實 MySQL 行為已驗證。測試通過也不代表正式排程或外部服務正常。

## 3. 新增或修改功能

先讀 [專案工作規則](PROJECT-RULES.md)、本次涉及的 `openspec/specs/` 及程式，再建立變更：

```text
npm run workflow -- new <change-name>
```

依 `openspec/schemas/integrated/templates/` 填寫提案、規格、設計、任務及審查。只維護本次變更的 `tasks.md`；Python 測試名稱使用 `test_R1_情境` 或 `test_D1_情境`，對應需求與技術檢查。

審查完成、關鍵問題已釐清且測試檔已存在及登錄後，執行：

```text
npm run workflow -- check <change-name>
```

完成實作與任務後，再執行：

```text
npm run workflow -- verify <change-name>
npm run workflow -- archive <change-name>
```

- `check` 核對文件、覆蓋對應、規格基準與衝突，不等於功能驗收。
- `verify` 真正執行測試並保存結果。失敗、跳過、零案例或測試期間檔案變動都不能通過。
- `archive` 核對最新證據、重跑測試並同步規格；正式規格通過嚴格驗證後才產生回條。不可直接使用原生 archive 繞過檢查。

正式規格在開發期間改變時，先比對差異，再執行 `npm run workflow -- rebase <change-name>`、重新審查及驗證。已封存的功能要再改時，建立新變更，保留舊紀錄。

## 4. 哪些資料需要保留

| 位置 | 用途 |
|---|---|
| `arxiv_digest/`、`tests/` | 正式程式與離線功能測試 |
| `scripts/`、`package*.json`、`workflow.config.json` | 已接入的工作流程工具與設定 |
| `openspec/specs/`、`openspec/changes/archive/` | 現行規格與歷史變更 |
| `.workflow/baselines/`、`evidence/`、`receipts/` | 歷史基準、原始驗證輸出及封存回條 |
| `.workflow/maintenance/` | 整理作業的獨立驗證紀錄，不取代功能變更回條 |

歷史證據可能含當時試驗副本的路徑，不能當作現在原專案剛跑完的結果。不得竄改其中的歷史事實、測試結果或決策；為保護隱私可移除個人電腦路徑，但須留下修改紀錄，並標示修改後證據的驗證限制。試驗過程檔已另行封存，位置與本次驗證結果見 [整理紀錄](docs/MAINTENANCE-2026-09-27.md)。

`config.ini` 是本機設定，不提交 Git。`node_modules/` 與 Python 快取可重新建立，不作為原始碼保存。Git 與專案資料夾備份不包含外部 MySQL 資料庫。

## 5. 純文件整理與限制

此版本不支援純文件、沒有行為差異的 OpenSpec 變更。這類整理使用 Git 紀錄、文件檢查及既有離線測試；不要虛構功能需求，也不得竄改已封存 verify／archive 證據中的歷史事實、測試結果或決策；僅為保護隱私移除個人電腦路徑時，須留下修改紀錄並標示驗證限制。

目前僅支援所列測試方式及本機工作流程；既有流程的通用自動升級尚未提供。若 archive 最後的正式規格驗證失敗，檔案可能已同步或封存，需檢查並以後續變更修正，不盲目重跑舊 archive。

工具能核對結構、連結與執行結果，不能自動證明需求合理、測試語意完整或資料庫寫入完整性。部署、資料遷移及外部服務操作需另行安排。

方法來源：OpenSpec 管理變更；模板參考 BMAD 的規劃方法與 Spec Kit 的澄清及一致性檢查方法，未安裝後兩者的原生工具。
