# 原專案整理與離線驗證紀錄

日期：2026-09-27。本次整理原 arxiv-digest，保存先前已套用但尚未提交的抓取修正、測試及工作流程；未新增產品行為。

## 備份與封存

整理前的完整備份位於專案旁的 `arxiv-digest-backups/20260927-014336/arxiv-digest-before-cleanup.zip`，包含 Git 歷史、原有未提交內容、本機設定及套件。2,724 個檔案已逐檔核對 SHA-256。這是本機備份，不納入本專案的 Git。

原 `.workflow/` 下的 `source-snapshot.json`、`trial-baseline.json`、`trial-baseline.log`、`trial-fixed.json`、`trial-fixed.log`、`followup-rebase.json` 共 6 份試驗過程檔，移到同一備份目錄的 `trial-process/`，並保留來源及雜湊清單。

資料夾備份不包含外部 MySQL 資料庫或 Windows 排程設定。原 `config.ini` 保持原樣且繼續排除版控。

## 正式內容

- 保留抓取上限探查、失敗續抓起點與 UTC 錯誤提示等既有修正。
- 保留正式程式、14 項測試、OpenSpec 工具、現行規格及兩筆歷史封存；未改寫舊證據。
- 正式驗證日誌納入版控，`.gitattributes` 保留 `.workflow/` 的原始位元組，避免換行轉換破壞日誌雜湊。
- 更新 README 與開發手冊，區分已實作抓取、尚未開發的推送／評分，以及第一版流程的實際操作方式。
- 保留既有 `config.ini.example` 修改；Telegram 範例設定不表示推送功能已實作。
- 本次核對 52 個程式、設定、測試及歷史檔案，內容與整理前完全一致。

## 本次驗證

- 重新執行 14 項離線功能測試，全數通過，涵蓋 R1～R4。
- 正式規格通過 OpenSpec 嚴格驗證。
- 原始結果：[離線測試](../.workflow/maintenance/2026-09-27/offline-tests.json)、[測試輸出](../.workflow/maintenance/2026-09-27/offline-tests.log)、[規格檢查](../.workflow/maintenance/2026-09-27/spec-validation.json)。

本輪使用既有 Python 套件環境，沒有驗證全新環境依固定版本重建。測試採模擬回應及記憶體資料庫，不連線 arXiv、MySQL 或 Telegram；未執行抓取、部署或排程修改。

歷史證據內的試驗副本路徑保留原樣，本次結果另存 `.workflow/maintenance/2026-09-27/`。這是純文件與檔案整理，不虛構功能 delta、不重新封存舊變更，也不把本紀錄當成新的功能交付回條。
