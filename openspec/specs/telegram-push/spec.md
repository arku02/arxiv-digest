# telegram-push Specification

## Purpose
每天把少量隨機抽樣的新論文推送到使用者的 Telegram，並在每則訊息附上回饋按鈕，讓推送管道同時成為建立無偏差標註資料的介面。

## Requirements

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
每篇論文 SHALL 以一則 HTML 格式訊息送出。沒有翻譯時，訊息 SHALL 依序包含粗體標題、作者（最多前 3 位，超過時註明總人數）、分類、摘要前 300 字（超過時以 … 結尾）與不含版本號的 https://arxiv.org/abs/<arxiv_id> 連結。有翻譯時（R6），訊息 SHALL 依序包含粗體中文標題、英文原標題、作者、分類、中文摘要（超過 1500 字時截斷並以 … 結尾）與同一連結，且不含英文摘要。文字 SHALL 經 HTML 跳脫並合併多餘空白，SHALL 關閉連結預覽。訊息 SHALL 附一列三個按鈕：👎 沒興趣、👍 有興趣、⭐ 超想讀，callback data 分別為 fb:<paper_id>:0、fb:<paper_id>:1、fb:<paper_id>:2。

#### Scenario: Message content
- **WHEN** 推送一篇標題含 < 與 &、作者 5 位、摘要 500 字的論文
- **THEN** 訊息標題已跳脫、列出前 3 位作者並註明共 5 人、摘要截為 300 字加 …、連結不含版本號，並附三個對應 callback data 的按鈕

#### Scenario: Translated message content
- **WHEN** 推送一篇已取得中文翻譯的論文，中文內容含 < 與 &
- **THEN** 訊息以跳脫後的粗體中文標題開頭，下一行為英文原標題，接著作者、分類、完整中文摘要與連結，不含英文摘要，按鈕與未翻譯時相同

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

### Requirement: R6 - Local translation
[TRANSLATE] 啟用時，push 與 push --dry-run SHALL 對每篇被抽中的論文，把合併空白後的英文標題與完整摘要送到設定的 Ollama 位址（預設本機 http://127.0.0.1:11434）與模型（預設 qwen3.5:9b），要求以 JSON 回傳台灣用語繁體中文的 title_zh 與 summary_zh，並以 R2 的翻譯格式送出。請求 SHALL 關閉模型思考模式與串流。每篇論文 SHALL 最多送出一次翻譯請求。

#### Scenario: Translated push
- **WHEN** 翻譯已啟用且抽中 3 篇論文
- **THEN** 送出 3 次翻譯請求，內容含各篇標題與摘要，3 則 Telegram 訊息都是中文格式

#### Scenario: Translated preview
- **WHEN** 翻譯已啟用時執行 push --dry-run
- **THEN** 印出的內容為中文格式，沒有 Telegram 請求

### Requirement: R7 - Fallback to English
翻譯請求連線失敗、逾時、回應錯誤，或回傳內容不是含非空 title_zh 與 summary_zh 的 JSON 時，該篇論文 SHALL 以未翻譯的英文格式送出並記錄警告。第一次翻譯失敗後，同一次 push 其餘論文 SHALL 不再送出翻譯請求，直接以英文格式送出。翻譯失敗 SHALL 不使本批失敗，不影響推送紀錄與退出碼。

#### Scenario: Ollama not running
- **WHEN** 翻譯已啟用但 Ollama 未執行，抽中 10 篇
- **THEN** 只送出 1 次翻譯請求，10 則訊息皆為英文格式，本批成功，記錄警告

#### Scenario: Failure mid batch
- **WHEN** 第 2 篇的翻譯回傳無效內容
- **THEN** 第 1 篇為中文格式，第 2 篇起為英文格式，共送出 2 次翻譯請求

### Requirement: R8 - Translation settings
[TRANSLATE] 區段 SHALL 為選用；區段不存在或 enabled 為 false 時 SHALL 不送出任何翻譯請求，行為與未加入翻譯前相同。enabled 不是可辨識的布林值，或 timeout 不是正數時，push SHALL 在連線資料庫前失敗並指出設定名稱。[TRANSLATE] 設定錯誤 SHALL 不影響 daily、backfill、collect 與 status。model 預設 qwen3.5:9b，url 預設 http://127.0.0.1:11434，timeout 預設 300 秒。

#### Scenario: Disabled by default
- **WHEN** config.ini 沒有 [TRANSLATE] 區段
- **THEN** push 不送出翻譯請求，訊息為英文格式

#### Scenario: Invalid settings
- **WHEN** enabled 為 maybe 或 timeout 為 0
- **THEN** push 退出碼為 1、錯誤指出該設定且未連線資料庫；daily 照常執行

### Requirement: R9 - Traditional Chinese normalization
翻譯成功後、組成訊息前，系統 SHALL 對 title_zh 與 summary_zh 進行正規化：不屬於 Big5 常用字（A440～C67E 區段）的漢字，若 OpenCC s2tw 可將其轉為常用字，SHALL 替換為轉換結果；Big5 常用字 SHALL 不被改動。接著 SHALL 依固定對照表替換下列大陸用語：視頻→影片、音頻→音訊、實時→即時、代碼→程式碼、信號→訊號、信息→資訊、網絡→網路、數據集→資料集、魯棒性→穩健性、算法→演算法（已是「演算法」時不重複替換）。英文內容與未翻譯的訊息 SHALL 不受影響。

#### Scenario: Simplified characters fixed
- **WHEN** 模型回傳「该方法这个数据的情况」
- **THEN** 訊息中為「該方法這個數據的情況」

#### Scenario: Valid Traditional text untouched
- **WHEN** 模型回傳「干擾、證明了、台灣、文件與參數、更多任務、演算法」
- **THEN** 訊息中的內容完全相同

#### Scenario: Mainland terms replaced
- **WHEN** 模型回傳「以算法處理視頻與實時信號」
- **THEN** 訊息中為「以演算法處理影片與即時訊號」

### Requirement: R10 - Hold push after failed fetch
非預覽的 push SHALL 在抽樣前讀取最近一筆執行紀錄。狀態為 failed 或 running 時 SHALL 不呼叫 Telegram、不建立批次，記錄說明最近一次抓取未成功並回傳退出碼 1；候選池下界 SHALL 不變，抓取成功後的下一次 push 候選池包含這段期間入庫的論文。沒有執行紀錄或最近一筆為 success 時 SHALL 依 R1 推送。push --dry-run 遇到相同情況 SHALL 只記錄警告並照常預覽。

#### Scenario: Latest fetch failed
- **WHEN** 最近一筆執行紀錄為 failed 時執行 push
- **THEN** 退出碼為 1，沒有 Telegram 請求，push_batches 沒有新增

#### Scenario: Push resumes after recovery
- **WHEN** 上述情況後重新抓取成功，再執行 push
- **THEN** 候選池包含上次成功批次後入庫、尚未推送的論文，依 R1 推送

#### Scenario: Preview still works
- **WHEN** 最近一筆執行紀錄為 failed 時執行 push --dry-run
- **THEN** 印出預覽，退出碼為 0，並記錄警告
