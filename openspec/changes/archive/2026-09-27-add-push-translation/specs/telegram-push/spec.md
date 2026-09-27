## MODIFIED Requirements

### Requirement: R2 - Message with feedback buttons
每篇論文 SHALL 以一則 HTML 格式訊息送出。沒有翻譯時，訊息 SHALL 依序包含粗體標題、作者（最多前 3 位，超過時註明總人數）、分類、摘要前 300 字（超過時以 … 結尾）與不含版本號的 https://arxiv.org/abs/<arxiv_id> 連結。有翻譯時（R6），訊息 SHALL 依序包含粗體中文標題、英文原標題、作者、分類、中文摘要（超過 1500 字時截斷並以 … 結尾）與同一連結，且不含英文摘要。文字 SHALL 經 HTML 跳脫並合併多餘空白，SHALL 關閉連結預覽。訊息 SHALL 附一列三個按鈕：👎 沒興趣、👍 有興趣、⭐ 超想讀，callback data 分別為 fb:<paper_id>:0、fb:<paper_id>:1、fb:<paper_id>:2。

#### Scenario: Message content
- **WHEN** 推送一篇標題含 < 與 &、作者 5 位、摘要 500 字的論文
- **THEN** 訊息標題已跳脫、列出前 3 位作者並註明共 5 人、摘要截為 300 字加 …、連結不含版本號，並附三個對應 callback data 的按鈕

#### Scenario: Translated message content
- **WHEN** 推送一篇已取得中文翻譯的論文，中文內容含 < 與 &
- **THEN** 訊息以跳脫後的粗體中文標題開頭，下一行為英文原標題，接著作者、分類、完整中文摘要與連結，不含英文摘要，按鈕與未翻譯時相同

## ADDED Requirements

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
