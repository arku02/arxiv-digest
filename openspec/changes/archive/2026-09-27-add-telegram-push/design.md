# 技術設計

## 已知事實
- 來源 commit ed4831beb6bb25e9ad606ac8ea4140807ee19a35。專案尚無 notifier.py；config.ini.example 已有 [TELEGRAM] bot_token、chat_id、daily_limit，但 config.py 未讀取。
- papers.created_at 為 MySQL CURRENT_TIMESTAMP，實測為伺服器本地時間（UTC+8），與程式使用的 naive UTC 不同；runs 的時間則由程式寫入 UTC。
- authors 以 id 順序保存作者順序；papers.link 含版本號（http://arxiv.org/abs/2609.29225v1）。每篇作者平均 5.7 位，最多 593 位；摘要常見 1000～1600 字元。
- feedback 表目前 0 筆，label 註解為 1／0；三級語意由 add-feedback-collect 正式調整。本變更只固定按鈕 callback data。
- 本機 config.ini 的 bot_token、chat_id 仍為範例值。

## 假設與待決問題
- 假設單一排程執行 push，不處理兩個 push 同時執行。
- 假設 Telegram 單一聊天每秒 1 則不會觸發限流；每則間隔 1 秒，10 則約 10 秒。
- 無待決業務問題：篇數、按鈕與收集方式已由使用者決定（見 proposal）。

## 擬採方案與取捨
- 時間基準：批次起點取自資料庫 SELECT CURRENT_TIMESTAMP，與 created_at 同一時鐘，避免 UTC 與本地時間混用。首次 24 小時下界在 Python 由該值減一天。
- 候選池：以最近一次成功批次起點為下界，失敗或中斷的批次不推進下界，與 runs 的續抓策略一致。抽樣在 Python 以 random.Random.sample 對排序後的 id 進行，可注入亂數來源測試；不用 MySQL RAND()，SQL 也能在 SQLite 測試。
- 記錄候選數：P3 評估可用 daily_limit／候選數還原每篇被抽中的機率，週一候選多、週末少的差異可以加權修正。
- 每則成功後立即 commit pushes，發送失敗時已送出的不會遺失，也不會重送。代價是失敗當天少於 10 篇，下一批會從剩餘候選重新抽。
- TelegramClient 以 requests.Session.post 呼叫 sendMessage；所有例外轉成 TelegramError 並把 token 換成 <bot_token>，以 from None 切斷例外鏈，避免 traceback 帶出網址。
- 設定：TelegramConfig 保存原始字串，push 時才驗證 daily_limit 與憑證；load_config 讀取 [TELEGRAM] 不會失敗，daily 不受影響。
- 替代方案：MySQL ORDER BY RAND() LIMIT 較短，但無法在離線測試驗證、也無法注入亂數；常駐 bot 已由使用者否決。

## 架構與資料影響
- 新增 arxiv_digest/notifier.py：TelegramClient、format_message、keyboard。
- cli.py 新增 push [--dry-run] 與 run_push 流程；store.py 新增 push_batches、pushes 兩表及查詢方法，init_schema 自動建立，不動既有表。
- push_batches(id, started_at, pool_size, sent, status, error, finished_at)；pushes(id, batch_id, paper_id UNIQUE, chat_id, message_id, pushed_at)，paper_id 與 batch_id 設外鍵。(chat_id, message_id) 建索引供之後收集回饋對應。

### Check: D1 - Offline isolation and registration
tests/test_telegram_push.py 登錄於 workflow.config.json；測試禁止 requests 與 pymysql 實際連線，以 SQLite 執行 Store 的新查詢、以模擬 session 取代 Telegram，不讀取 config.ini。

## 驗證與回復
- Python unittest：R1～R5 與 D1 對應 test_R*/test_D1_ 方法；SQLite 只驗證查詢邏輯，不代表 MySQL 實機驗證；Telegram 以模擬回應驗證，不代表真實 bot 已可推送。
- 實機驗證由使用者填入 token 後以 push --dry-run、push 各執行一次確認，不列為本變更的自動測試。
- 回復：停用排程中的 push 即可；新表可保留，不影響抓取。
