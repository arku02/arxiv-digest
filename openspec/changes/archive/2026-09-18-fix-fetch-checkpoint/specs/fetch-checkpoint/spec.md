## Purpose
確保抓取上限不讓尚未完成的時間區間被當成成功，並提供可重試的起點。

## ADDED Requirements

### Requirement: R1 - Complete fetch
系統 SHALL 在有效設定下，保留未達上限的分頁抓取、空結果成功與既有去重行為。空時間區間 SHALL 不發送請求。

#### Scenario: Complete fetch acceptance
- **WHEN** 取回筆數未達 max_results 或沒有結果
- **THEN** 完整結果交由既有儲存流程處理，成功起點推進至區間終點

### Requirement: R2 - Detect incomplete window
系統 SHALL 在取回 max_results 筆後，以相同查詢在下一個 offset 探查最多一筆。若探查為空 SHALL 視為完整；若仍有論文或探查失敗 SHALL 失敗且不儲存這批部分結果，不標記該區間 success。page_size 或 max_results 非正整數 SHALL 在請求前拒絕。上限限制交付資料筆數，探查額外最多取得一筆，不入庫。

#### Scenario: Detect incomplete window acceptance
- **WHEN** 完整上限批次後的探查仍有一筆
- **THEN** 這次執行失敗，原成功起點保留；空探查則允許完成

### Requirement: R3 - Preserve retry start
daily SHALL 從最新成功終點與尚未被後續成功區間完整覆蓋之 failed/running 區間起點中選最早值。兩者皆不存在才使用 initial_backfill_days。成功覆蓋 SHALL 具有較大的執行 id，且起點不晚於失敗起點、終點不早於失敗終點。首次失敗、未完成執行及較早 backfill 失敗 SHALL 可重新抓取；重試重複資料沿用 arxiv_id 去重。

#### Scenario: Preserve retry start acceptance
- **WHEN** 第一次執行未完成，隔日提高上限後重跑
- **THEN** 沿用先前保存起點，成功涵蓋後才向前推進

### Requirement: R4 - Actionable failure
未完成的 daily 指令 SHALL 回傳非零退出碼，錯誤 SHALL 說明起點保留、調高 max_results 後重跑。不得把這次上限中止描述為完整成功。

#### Scenario: Actionable failure acceptance
- **WHEN** 抓取超過上限
- **THEN** 退出碼為 1 且錯誤包含起點保留及重跑方法
