# 推送訊息中文翻譯

## Why
使用者表示推送訊息全是英文、專業術語多，看不懂就無法判斷是否有興趣，回饋品質也會受影響。使用者要求免費方案。

使用者決定（2026-09-27）：以本機 Ollama 執行免費開源模型；格式為「中文標題＋完整中文摘要」，保留英文原標題與連結。

試翻紀錄（2026-09-27，同 3 篇 cs.AI／cs.CL／cs.CV 論文，手動比對，非自動測試）：
- qwen3.5:4b：每篇約 25 秒，有「基於精簡」（distillation）、「四個五個」（four of five）等誤譯與多處大陸用語。
- qwen3.5:9b 加台灣用語對照：每篇約 46 秒，上述誤譯消失，只剩少數生硬直譯；使用者選用此組合。
- 對照表中含 four of five 範例，該句的改善不能完全歸因於模型。

成功標準：每天推送的論文以台灣繁體中文呈現標題與摘要；翻譯失敗時仍照常推送英文版，不漏推、不影響回饋。

## What Changes
- 新增 [TRANSLATE] 設定（預設關閉）：啟用後 push 與 push --dry-run 以本機 Ollama 模型翻譯被抽中論文的標題與完整摘要。
- 訊息格式：有翻譯時為粗體中文標題、英文原標題、作者、分類、完整中文摘要、連結；無翻譯時維持現行英文格式。按鈕不變。
- 翻譯失敗時該篇改推英文，並停止本批其餘論文的翻譯請求，避免逐篇等待逾時。
- 採 full：修改既有訊息格式需求並新增外部服務（本機 Ollama）互動。

## Non-goals
- 不保存翻譯結果、不翻譯未推送的論文、不翻譯作者或分類。
- 不安裝 Ollama 或下載模型（已由使用者同意另行完成），不支援 Claude、DeepL 等付費或雲端翻譯。
- 不改變抽樣、推送紀錄、回饋收集與 status。

## Capabilities
### New Capabilities
- 無
### Modified Capabilities
- telegram-push: 修改 R2（有翻譯時的訊息格式）；新增 R6 本機翻譯、R7 翻譯失敗退回英文、R8 翻譯設定。

## Impact
新增 arxiv_digest/translator.py；修改 config.py、notifier.py（format_message 支援翻譯）、cli.py（push 流程）、config.ini.example、README.md；新增 tests/test_push_translation.py 並登錄 workflow.config.json。

每日 push 由約 10 秒增為約 8 分鐘；執行期間 Ollama 約占 7～8 GB 記憶體，結束後 1 分鐘內釋放。
