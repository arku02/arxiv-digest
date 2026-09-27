## MODIFIED Requirements

### Requirement: R3 - Preserve retry start
daily SHALL 從「最新成功終點往前 lookback_days 天」與尚未被後續成功區間完整覆蓋之 failed/running 區間起點中選最早值。failed/running 區間起點 SHALL 直接沿用，不再往前加 lookback_days。兩者皆不存在才使用 initial_backfill_days，首次回溯不另加 lookback_days。成功覆蓋 SHALL 具有較大的執行 id，且起點不晚於失敗起點、終點不早於失敗終點。首次失敗、未完成執行及較早 backfill 失敗 SHALL 可重新抓取；重試與回看的重複資料沿用 arxiv_id 去重。

#### Scenario: Preserve retry start acceptance
- **WHEN** 第一次執行未完成，隔日提高上限後重跑
- **THEN** 沿用先前保存起點，成功涵蓋後才向前推進

#### Scenario: Repeated failures keep the same start
- **WHEN** 已有成功紀錄後，連續兩次 daily 都未完成，第三次才成功
- **THEN** 三次執行的查詢起點相同，都是該成功終點往前 lookback_days 天

## ADDED Requirements

### Requirement: R5 - Announcement lag lookback
arXiv API 在論文公告前查不到該論文。daily SHALL 依 R3 每次重新查詢最新成功終點前 lookback_days 天，使前次執行時尚未公告的論文在公告後的下一次 daily 入庫。lookback_days SHALL 預設為 4；設為 0 時起點與未回看時相同。lookback_days 不是非負整數時 SHALL 在連線資料庫與發送請求前拒絕。回看取回的既有論文 SHALL 以 arxiv_id 去重，新增筆數只計入新論文。backfill 指定天數時 SHALL 以指定起點查詢，不另加 lookback_days。

#### Scenario: Paper announced after an earlier run
- **WHEN** 週五提交的論文在週六、週日 daily 執行時尚未公告，週一公告後再執行 daily
- **THEN** 週一的查詢區間包含該論文提交時間，論文入庫

#### Scenario: Lookback disabled
- **WHEN** lookback_days 為 0，其餘條件同上
- **THEN** 查詢起點等於最新成功終點，週一執行不包含該論文

#### Scenario: Overlap is deduplicated
- **WHEN** 回看區間內的論文已在前一次 daily 入庫
- **THEN** 這些論文不重複入庫，新增筆數只計新論文

#### Scenario: Invalid lookback rejected
- **WHEN** lookback_days 為負數或非整數
- **THEN** 讀取設定即失敗，daily 回傳非零退出碼，不連線資料庫、不發送請求

#### Scenario: Backfill keeps explicit start
- **WHEN** 執行 backfill --days 7
- **THEN** 查詢起點為執行時間往前 7 天，不另加 lookback_days
