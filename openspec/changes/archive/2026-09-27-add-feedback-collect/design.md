# 技術設計

## 已知事實
- 來源 commit 8998a5d。notifier.keyboard 產生 fb:<paper_id>:<0|1|2>；pushes 保存 (batch_id, paper_id UNIQUE, chat_id, message_id)，(chat_id, message_id) 已建索引。
- feedback 表有 paper_id UNIQUE、label TINYINT、created_at，目前 0 筆；註解仍寫 1／0。
- 2026-09-27 首批 10 則已送出，message_id 2～11；bot 的佇列中另有使用者按 Start 時送出的 /start 文字訊息。
- Telegram getUpdates 以 offset 確認更新：呼叫時帶 offset = 最後處理的 update_id + 1，較舊的更新即被確認；未確認的更新保留 24 小時。answerCallbackQuery 只能在點擊後短時間內呼叫。
- pymysql 預設的 UPDATE 影響列數不含「值相同」的列，不能用 UPDATE 影響列數判斷是否已存在。

## 假設與待決問題
- 假設單一排程執行 collect，不處理兩個 collect 同時執行。
- 假設所有推送都在私人聊天，callback 的 message.chat.id 等於設定的 chat_id。
- 無待決業務問題：三級語意與每小時收集已由使用者決定。

## 擬採方案與取捨
- 讀取：迴圈呼叫 getUpdates(offset, timeout=0, limit=100, allowed_updates=["callback_query"])，每批處理完再以下一個 offset 呼叫，下一次呼叫即確認上一批；取得空批次時結束。處理中途失敗就直接拋出，不再呼叫 getUpdates，該批不被確認而於下次重送。
- 寫入：先 SELECT 既有 label，不存在則 INSERT，不同則 UPDATE，相同則略過，每筆 commit。不用 MySQL 專屬的 ON DUPLICATE KEY，SQL 也能在 SQLite 測試，重送時結果相同。
- 驗證：data 以 ^fb:(\d+):([012])$ 解析；chat_id 以字串比對設定值；以 (chat_id, message_id) 查 pushes 取得 paper_id，須與 data 一致，防止偽造或誤對。
- 按鈕：keyboard(paper_id, selected) 在選擇的按鈕前加 ✅，editMessageReplyMarkup 失敗只警告。「message is not modified」視為成功，重送時不會產生警告。
- 不呼叫 answerCallbackQuery：每小時收集時一定逾時，多一次請求只會得到錯誤。
- API 呼叫抽成 TelegramClient._call，sendMessage、getUpdates、editMessageReplyMarkup 共用錯誤處理與 token 遮蔽；push 行為不變，由既有 push 測試確認。
- collect 只驗證憑證，不驗證 daily_limit。
- 替代方案：資料庫自存 offset。Telegram 本身保存確認狀態，自存 offset 只會多一份需要同步的狀態，因此不採用。

## 架構與資料影響
- 不新增資料表或欄位；feedback.label 的 schema 註解改為 0=沒興趣、1=有興趣、2=超想讀。既有表的註解不會自動更新，不影響資料。
- store.py 新增 pushed_paper_for_message、save_feedback、feedback_summary；cli.py 新增 collect 與 status 摘要；notifier.py 新增 get_updates、edit_markup。

### Check: D1 - Offline isolation and registration
tests/test_feedback_collect.py 登錄於 workflow.config.json；禁止 requests 與 pymysql 實際連線，以 SQLite 執行 Store 的新查詢、以模擬 Bot API 提供更新佇列與 offset 確認語意，不讀取 config.ini。

## 驗證與回復
- Python unittest：R1～R5 與 D1 對應 test_R*/test_D1_ 方法；既有 38 項測試須全數通過。SQLite 與模擬 API 不代表 MySQL 或真實 Telegram 已驗證。
- 實機確認：使用者按下首批訊息的按鈕後，執行一次 collect 與 status，在變更封存前確認。
- 回復：停用排程中的 collect 即可；已寫入的 feedback 保留。
