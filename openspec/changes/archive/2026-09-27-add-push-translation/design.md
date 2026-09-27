# 技術設計

## 已知事實
- 來源 commit 3237b8d。notifier.format_message(paper) 產生英文訊息；cli.run_push 逐篇 format_message → client.send → record_push，dry-run 只印出內容。
- 本機已安裝 Ollama 0.34.4（http://127.0.0.1:11434）與 qwen3.5:9b（6.6 GB）；qwen3.5:4b 已依使用者要求刪除。
- 試翻時使用 /api/chat，stream=false、think=false、format 為 JSON schema、temperature 0.2、num_ctx 4096；9b 每篇約 46 秒，首篇含載入約 83 秒，速度約 6.4 token/s（CPU）。
- 試翻的中文摘要長度 326～557 字；arXiv 摘要上限約 1920 字元，Telegram 單則訊息上限 4096 字元。
- 本機硬體：i7-12700H、16 GB 記憶體、Intel Arc A370M（Ollama 以 CPU 執行）。

## 假設與待決問題
- 假設 Ollama 常駐並於開機時啟動（安裝程式預設行為）；未執行時依 R7 退回英文。
- 假設中文摘要不超過 1500 字；超過時截斷，訊息仍在 Telegram 上限內。
- 無待決業務問題：模型、格式與免費方案已由使用者決定。

## 擬採方案與取捨
- 新增 translator.py：TranslateConfig 驗證後的設定建立 OllamaTranslator，以 requests.Session.post 呼叫 /api/chat。專案已有 requests，不新增套件；Ollama 官方 Python 套件只是薄包裝，不值得多一個依賴。
- 提示詞沿用試翻版本：台灣用語、專有名詞「中文（English）」、沒把握的術語保留英文、對照表與數字精確要求。temperature 0.2 降低隨機性。
- keep_alive 設 60 秒：批次內逐篇呼叫會延續載入，推送結束約 1 分鐘後釋放 7～8 GB 記憶體。
- 斷路：第一次失敗後本批不再翻譯。Ollama 未執行或模型逾時多半是持續性問題，逐篇重試最壞要等 10 × 300 秒。代價是暫時性錯誤會讓當批其餘論文都是英文。
- 格式：format_message(paper, translation=None)。翻譯存在時改用中文格式，先截斷再跳脫；不存在時輸出與原本完全相同，既有推送測試不需修改。
- 設定沿用 TelegramConfig 模式：TranslateConfig 保存原始字串，push 時才驗證，daily 等指令不受影響。布林值用 ConfigParser 的標準寫法（true/false、yes/no、on/off、1/0）。
- 不保存翻譯：目前只有推送時需要；P3 若需要中文內容再另行設計。
- 替代方案：Claude API 或 DeepL 品質較好、速度較快，但使用者要求免費；qwen3.5:4b 較快但誤譯多，已比較並排除。

## 架構與資料影響
- 不新增資料表。config.ini.example 新增 [TRANSLATE]（enabled = false，附說明）；本機 config.ini 由交付時另行開啟。
- Config 新增 translate 欄位，預設為關閉的 TranslateConfig，既有建構 Config 的程式與測試不受影響。

### Check: D1 - Offline isolation and registration
tests/test_push_translation.py 登錄於 workflow.config.json；禁止 requests 與 pymysql 實際連線，以模擬 Ollama 與 Bot API 回應驗證，不讀取 config.ini、不需要本機 Ollama。

## 驗證與回復
- Python unittest：R2、R6～R8、D1 對應 test_R*/test_D1_ 方法；既有 53 項測試須全數通過，其中英文格式測試不修改。模擬回應不代表真實模型的翻譯品質。
- 實機確認：封存前以本機 qwen3.5:9b 執行 push --dry-run 與一次 push，由使用者確認手機顯示。
- 回復：在 config.ini 設 enabled = false 即恢復英文推送，不需改程式。
