# feedback-collect Specification

## Purpose
讀取使用者在 Telegram 推送訊息上按下的回饋按鈕，存成每篇論文一筆的三級標註，並讓使用者在訊息與 status 看到收集結果，作為之後評估與個人化的資料。

## Requirements

### Requirement: R1 - Collect button feedback
collect SHALL 以 getUpdates 讀取所有待處理更新，依 update_id 順序處理 callback data 為 fb:<paper_id>:<label> 的按鈕點擊，label 0、1、2 分別代表沒興趣、有興趣、超想讀。每篇論文 SHALL 只保存一筆回饋，同一篇的後續點擊 SHALL 覆蓋先前標籤，以最後處理者為準。更新 SHALL 在處理成功後才向 Telegram 確認，確認後不再重複取得。

#### Scenario: New feedback saved
- **WHEN** 使用者在已推送的訊息按下 👍 後執行 collect
- **THEN** feedback 新增該篇論文 label 1 的紀錄，再次執行 collect 不會取得同一筆更新

#### Scenario: Changed mind
- **WHEN** 同一篇論文先按 👎 再按 ⭐，之後才執行 collect
- **THEN** feedback 只有一筆，label 為 2

### Requirement: R2 - Ignore invalid updates
系統 SHALL 略過且不寫入以下更新：非按鈕點擊、chat 不是設定的 chat_id、callback data 格式不符或 label 不在 0～2、或 (chat_id, message_id) 找不到對應同一篇論文的推送紀錄。略過的更新 SHALL 一樣被確認，不阻擋後續更新，並在記錄中統計略過數量。

#### Scenario: Foreign or forged callback
- **WHEN** 更新中有別的聊天室的點擊、fb:5:9 這類無效資料，以及 paper_id 與推送紀錄不符的點擊
- **THEN** feedback 沒有新增，這些更新被確認，同批其他有效點擊照常寫入

### Requirement: R3 - Show recorded choice
回饋寫入後，系統 SHALL 編輯該則訊息的按鈕：目前標籤的按鈕文字前加上 ✅，三個按鈕與 callback data 保留，使用者仍可改按。Telegram 回覆訊息未變更時 SHALL 視為成功。按鈕編輯失敗 SHALL 只記錄警告，不影響已寫入的回饋與更新確認。

#### Scenario: Button marked
- **WHEN** collect 寫入 label 1
- **THEN** 該訊息按鈕變成 👎 沒興趣、✅ 👍 有興趣、⭐ 超想讀

#### Scenario: Edit failure tolerated
- **WHEN** 編輯按鈕時 Telegram 回傳錯誤
- **THEN** 回饋仍保存、更新仍被確認，collect 退出碼為 0 並記錄警告

### Requirement: R4 - Failure and idempotency
讀取更新或寫入資料庫失敗時，collect SHALL 回傳非零退出碼，且 SHALL 不確認尚未處理成功的更新，使其下次重送。重複處理同一批更新 SHALL 得到相同的回饋結果，不產生重複紀錄。bot_token 或 chat_id 缺少或仍為範例值時 SHALL 在連線資料庫前失敗；錯誤訊息 SHALL 遮蔽 bot token。daily_limit 無效時 SHALL 不影響 collect。

#### Scenario: Database failure redelivers
- **WHEN** 寫入第 2 筆回饋時資料庫發生錯誤
- **THEN** 退出碼為 1；下一次 collect 重新取得同一批更新，完成後每篇仍只有一筆回饋

### Requirement: R5 - Status summary
status SHALL 顯示已推送篇數、已回饋篇數、回饋率（回饋篇數除以推送篇數），以及 👎、👍、⭐ 各自的篇數。沒有推送紀錄時 SHALL 顯示 0 且不出錯。

#### Scenario: Summary after feedback
- **WHEN** 已推送 10 篇，其中 4 篇有回饋：1 篇 👎、2 篇 👍、1 篇 ⭐
- **THEN** status 顯示推送 10 篇、回饋 4 篇、回饋率 40%，以及 1／2／1 的分布
