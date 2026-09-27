## Purpose
每天把少量隨機抽樣的新論文推送到使用者的 Telegram，並在每則訊息附上回饋按鈕，讓推送管道同時成為建立無偏差標註資料的介面。

## ADDED Requirements

### Requirement: R1 - Random daily sample
push SHALL 以資料庫時間為本批起點，候選池為「入庫時間晚於最近一次成功批次起點、不晚於本批起點，且從未推送過」的論文；沒有成功批次時為本批起點前 24 小時內入庫者。系統 SHALL 從候選池均勻隨機抽取 min(daily_limit, 候選數) 篇，並記錄本批候選數。候選池為空時 SHALL 不發送訊息並將本批記為成功。

#### Scenario: Sample from new unpushed papers
- **WHEN** 上次成功批次後新入庫 25 篇，其中 2 篇已推送過，另有 5 篇早於上次成功批次，daily_limit 為 10
- **THEN** 從其餘 23 篇中隨機推送 10 篇，本批候選數記為 23

#### Scenario: Small pool
- **WHEN** 候選池只有 3 篇
- **THEN** 3 篇全部推送

#### Scenario: Empty pool
- **WHEN** 候選池為空
- **THEN** 不呼叫 Telegram，本批記為成功、推送 0 篇

### Requirement: R2 - Message with feedback buttons
每篇論文 SHALL 以一則 HTML 格式訊息送出，依序包含粗體標題、作者（最多前 3 位，超過時註明總人數）、分類、摘要前 300 字（超過時以 … 結尾）與不含版本號的 https://arxiv.org/abs/<arxiv_id> 連結。文字 SHALL 經 HTML 跳脫並合併多餘空白，SHALL 關閉連結預覽。訊息 SHALL 附一列三個按鈕：👎 沒興趣、👍 有興趣、⭐ 超想讀，callback data 分別為 fb:<paper_id>:0、fb:<paper_id>:1、fb:<paper_id>:2。

#### Scenario: Message content
- **WHEN** 推送一篇標題含 < 與 &、作者 5 位、摘要 500 字的論文
- **THEN** 訊息標題已跳脫、列出前 3 位作者並註明共 5 人、摘要截為 300 字加 …、連結不含版本號，並附三個對應 callback data 的按鈕

### Requirement: R3 - Push record and failure
每則訊息送出成功後 SHALL 立即記錄論文、chat_id、Telegram message_id 與批次，同一篇論文 SHALL 不被推送兩次。任一則發送失敗時 SHALL 停止本批、保留已送出紀錄、將本批記為失敗並回傳非零退出碼。失敗批次 SHALL 不推進候選池下界，下一次 push 的候選池仍包含本批未送出的論文。

#### Scenario: Pushed papers are not repeated
- **WHEN** 連續兩天執行 push
- **THEN** 第二天不會推送第一天已推送的論文

#### Scenario: Failure mid batch
- **WHEN** 第 4 則訊息發送失敗
- **THEN** 前 3 篇已記錄，本批為失敗、退出碼為 1；下一次 push 的候選池不含那 3 篇，但包含本批其他候選論文

### Requirement: R4 - Telegram settings and secrets
[TELEGRAM] 區段 SHALL 只在 push 時檢查，缺少或無效時 daily、backfill、status 不受影響。daily_limit SHALL 預設 10，非正整數時 push SHALL 在連線資料庫前失敗。非預覽模式下，bot_token 或 chat_id 缺少或仍為範例值時 SHALL 在連線資料庫前失敗，並提示在 config.ini 填入。bot_token SHALL 不出現在任何記錄、錯誤訊息或標準輸出中。Telegram 回應 403 時，錯誤 SHALL 提示先對 bot 按 Start。

#### Scenario: Placeholder credentials
- **WHEN** bot_token 仍為 YOUR_BOT_TOKEN_HERE 時執行 push
- **THEN** 退出碼為 1，錯誤提示在 config.ini 填入，且未連線資料庫

#### Scenario: Token is masked
- **WHEN** 網路錯誤訊息中含有 bot token
- **THEN** 記錄與錯誤訊息只顯示遮蔽後的文字

#### Scenario: Fetch unaffected
- **WHEN** config.ini 沒有 [TELEGRAM] 區段或 daily_limit 無效
- **THEN** 設定仍可讀取，daily 照常執行

### Requirement: R5 - Dry run preview
push --dry-run SHALL 依 R1 抽樣並把每則訊息內容與按鈕印到標準輸出，SHALL 不呼叫 Telegram、不寫入推送紀錄，且不需要 bot_token 與 chat_id。

#### Scenario: Preview before bot setup
- **WHEN** bot_token 仍為範例值時執行 push --dry-run
- **THEN** 印出抽中的訊息內容，退出碼為 0，沒有 Telegram 請求，也沒有新增批次或推送紀錄
