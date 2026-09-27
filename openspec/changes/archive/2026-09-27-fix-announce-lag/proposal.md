# 公告延遲回看

## Why
daily 以「上次成功終點 ~ 現在」的 submittedDate 區間查詢，但 arXiv API 要等論文公告後才查得到。排程執行時，區間尾端的論文多半尚未公告，API 回傳空結果仍被標記 success，續抓起點越過這段時間，之後不會再查。

事實（2026-09-27 查本機 MySQL）：
- runs 第 11～14 次（區間 2026-09-18 02:12 ~ 09-22 01:11 UTC）與第 18 次（09-25 06:45 ~ 09-27 06:08 UTC）都是 success、取回 0 筆。
- papers 中 published 為 09-18、09-19、09-20、09-21 的論文為 0 篇；README 實測同期平均約 194 篇／天，週一約 317 篇。
- 09-22～09-24 各存 140、112、130 篇，低於同星期實測值 287、221、222，推測每天尾端送出的論文也被略過。

推論（未以即時 API 驗證）：arXiv 平日約 14:00 ET 截止、20:00 ET 公告；週四截止後到週五截止前的投稿延到週日晚上公告，週五截止後的到週一晚上公告，最長約 3 天 6 小時，公告後 API 索引另有延遲（第 14 次在週一公告後約 71 分鐘執行仍取回 0）。

成功標準：論文提交後若在某次 daily 時尚未公告，只要之後在延遲上限內有另一次 daily，該論文就會入庫；重疊查詢不重複入庫。

## What Changes
- 新增設定 lookback_days（預設 4）：daily 查詢起點改為「最新成功終點往前 lookback_days 天」與待重試區間起點中的最早值。
- 失敗／執行中區間起點沿用原值，不再疊加回看，避免連續失敗時起點不斷往前漂移。
- lookback_days 非非負整數時，在連線資料庫及發送請求前拒絕。
- config.ini.example 加入 lookback_days，max_results 調為 2000；README 說明回看、流量與補抓方式。
- 採 lite：只調整既有 fetch-checkpoint 的起點計算並加一項設定，不動資料表與外部介面。

## Non-goals
- 不自動補回已漏抓的歷史資料；09-18 起的缺口由操作者另外執行 backfill。
- 不改用 OAI-PMH 或依公告時程計算區間，不處理 arXiv 假日停刊超過 lookback_days 的情況。
- 不自動調高 max_results，不修改本機 config.ini，不實作推送或評分。

## Capabilities
### New Capabilities
- 無
### Modified Capabilities
- fetch-checkpoint: 修改 R3（續抓起點納入回看）；新增 R5（公告延遲回看、設定驗證、重疊去重）。

## Impact
config.py、store.py、cli.py、config.ini.example、README.md、tests/test_fetch_checkpoint.py。

每次 daily 查詢範圍由約 1 天增為約 5 天，平日取回筆數約 800～1300 筆（多數為已入庫的重複），請求數約 10～13 次、耗時約 40 秒。本機 config.ini 的 max_results 若維持 1000，可能依 R2 回報失敗，需由操作者調高。
