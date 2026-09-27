# 抓取上限與續抓起點

## Why
目前達 max_results 後仍標記整段區間 success，未抓到的論文可能被略過。首次失敗若沒有 success 紀錄，每天重新計算回溯起點也會漂移。

## What Changes
- 保留既有完整抓取行為；達上限時額外探查一筆，區分剛好抓完與仍有剩餘。
- 尚有剩餘時回報失敗、不寫入這批部分資料、不推進成功起點。
- daily 納入尚未被後續完整成功覆蓋的 failed/running 區間起點。
- 加入離線 Python 驗收測試與整合流程。

## Capabilities
### New Capabilities
- fetch-checkpoint: R1～R4；既有專案尚無 OpenSpec 基準，本次首次建立此能力規格。

## Impact
fetcher.py、store.py、cli.py、README.md、離線測試與工作流程檔案。採 lite；不變更資料表或外部介面。

## Non-goals
不實作 Telegram、LLM 評分、自动拆分大量區間、並行抓取或正式部署。不保證搜尋索引變動時的快照一致性，不補救過往已被誤標 success 的資料。
