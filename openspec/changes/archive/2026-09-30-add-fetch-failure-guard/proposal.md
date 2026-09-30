# 抓取失敗時暫停推送並自動補抓

## Why
排程「arxiv-digest daily」依序執行 daily 與 push。daily 失敗時 push 照樣執行，候選池為空，送出 0 篇並記為成功；工作排程器只顯示最後一個動作的結果，使用者看到「成功」卻沒收到論文，也不知道原因。

事實（2026-09-30 查本機 MySQL）：
- runs 第 23 次（區間 2026-09-25 01:30 ~ 09-30 03:17 UTC）為 failed，錯誤為「arXiv API 連續 3 次請求失敗：HTTP 429」。
- push_batches 第 5 批於同一分鐘建立，pool_size 0、sent 0、status success。
- 同日 15:12（本機時間）手動重跑 daily 成功，取回 2558 筆、新增 1900 筆；再手動 push 送出 10 篇。
- fetcher 遇到失敗只等 3、6、12 秒重試（request_delay × 2ⁿ），對 429 來說過短，且最後一次失敗後仍多等一次。

成功標準：抓取失敗時使用者在 Telegram 收到一則說明，當天不會收到空推送；arXiv 恢復後在允許時段內自動補抓並推送，不需要使用者介入。

## What Changes
- fetcher 遇到 HTTP 429／503 時依 Retry-After（上限 300 秒）等待，沒有時等 60、120 秒；最後一次失敗後不再等待。
- daily 失敗時以 Telegram 發一則沒有按鈕的通知，同一段連續失敗只通知一次；Telegram 未設定或發送失敗不影響 daily 結果。
- push 發現最近一次抓取為 failed 或 running 時不推送、不建立批次，回傳非零退出碼。
- 每小時的 collect 收完回饋後檢查最近一次抓取：失敗且在 [RETRY] 允許時段（預設 10:00～22:00）內就重抓，成功則推送。
- 新增選用的 [RETRY] 設定區段（enabled、start_hour、end_hour）。
- 重試放進既有的每小時 collect，不新增 Windows 排程；排程修改需要系統管理員權限，使用者已確認偏好不必再改排程。
- 採 full：跨 fetch-checkpoint 與 telegram-push 兩個能力，新增外部通知與自動重試行為。

## Non-goals
- 不重試失敗的推送批次（telegram-push R3 已讓下一次 push 補上）。
- 最近一次抓取已成功但當天尚未推送時（例如手動重跑 daily 後沒有 push），不自動補推。
- 上限錯誤（max_results 不足）不自動重試，仍需操作者調整設定。
- 不修改 Windows 排程或本機 config.ini；不處理同一時間多個抓取程序互相覆蓋。

## Capabilities
### New Capabilities
- 無
### Modified Capabilities
- fetch-checkpoint: 新增 R6（限流等待）、R7（失敗通知）、R8（每小時補抓）。
- telegram-push: 新增 R10（抓取失敗時暫停推送）。

## Impact
fetcher.py、notifier.py、config.py、cli.py、config.ini.example、README.md；新增 tests/test_fetch_recovery.py 並登錄於 workflow.config.json；調整既有測試替身加入 runs 表。

不變更資料表。push 在最近一次抓取失敗時退出碼改為 1，排程器會顯示失敗，這是預期行為。collect 在補抓失敗時退出碼為 1。補抓成功時推送約需 10～20 分鐘（含本機翻譯），期間同一個 collect 程序持續執行。
