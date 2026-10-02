# 技術設計

## 已知事實
- 基準規格：openspec/specs/fetch-checkpoint/spec.md（R1～R8）。
- cli.notify_fetch_failure 讀 store.recent_runs(limit=2)，runs[1]（前一筆）status 為 failed 就不發送；不看錯誤類型。
- 上限錯誤以 fetcher.LIMIT_ERROR_PREFIX（「已達單次上限」）開頭；cli._needs_retry 已用同一前綴區分是否補抓。runs.error 保存錯誤前 500 字，前綴不會被截掉。
- 通知在 run_fetch 寫入本次 failed 之後才執行，所以 runs[0] 是本次、runs[1] 是前一筆。
- 2026-10-02 的事件經過見 proposal.md。

## 假設與待決問題
- 假設只需區分兩類（上限／非上限），因為通知的後續處理只有這兩種；非上限錯誤內部（429、逾時、500）處理相同，不再細分。
- 無待決業務問題。

## 擬採方案與取捨
- 新增 _is_limit_error(text) 判斷錯誤是否以 LIMIT_ERROR_PREFIX 開頭；notify_fetch_failure 只在前一筆為 failed 且 _is_limit_error(前一筆 error) 等於 _is_limit_error(本次錯誤) 時跳過。_needs_retry 改用同一函式，兩處判斷不會漂移。
- 本次類型以傳入的例外訊息判斷，不讀 runs[0]，與既有通知內容的判斷來源一致。
- 替代方案：比較完整錯誤文字。429 與逾時會被當成不同錯誤而重複通知，且錯誤含查詢時間，每次都不同；捨棄。
- 取捨：429 與上限錯誤交替出現時每次都會通知。此情況需要操作者介入，通知是預期行為。
- 已知限制沿用 R7：抓取在寫入 runs 前就失敗時，「前一筆」可能是更早的紀錄。

## 架構與資料影響
不變更資料表或設定。

## 驗證與回流
擴充 tests/test_fetch_recovery.py 的 R7 案例：429→上限、上限→429 皆通知；上限→上限不通知；既有 429→429 不通知的案例保留。R1～R8 與 telegram-push R10 完整回歸。

## 限制
離線驗證，未以真實 Telegram 或 MySQL 執行。
