# 收集推送回饋

## Why
add-telegram-push 已送出附三個按鈕的訊息（2026-09-27 首批 10 則），但按鈕點擊沒有被讀取。Telegram 只保留尚未讀取的更新 24 小時，不收集就會遺失。P3 需要這些標註來衡量評分準確度。

成功標準：使用者按下按鈕後，下一次 collect 會把該篇的回饋存入 feedback；改按其他按鈕以最後一次為準；訊息按鈕顯示目前選擇；status 可看到回饋率。

使用者決定（2026-09-27）：三級回饋 👎 0／👍 1／⭐ 2；以每小時排程執行 collect，不使用常駐程式。

## What Changes
- 新增 collect 指令：以 getUpdates 讀取按鈕點擊，驗證後寫入 feedback，處理完才確認更新。
- 只接受來自設定 chat_id、且對應到已推送訊息的點擊；其他更新略過並確認。
- 寫入後編輯該則訊息的按鈕，在目前選擇前加 ✅，其他按鈕仍可改按。
- status 顯示推送篇數、回饋篇數、回饋率與三級分布。
- feedback.label 語意改為 0／1／2（現有 0 筆資料，不需轉換）。
- 採 full：新增外部 API 互動與回饋資料的寫入規則。

## Non-goals
- 不即時回應按鈕（不呼叫 answerCallbackQuery）；每小時收集時查詢早已逾時，按鈕會短暫轉圈後停止。
- 不保存回饋變更歷史，不新增欄位；feedback.created_at 保留第一次回饋時間。
- 不建立或修改 Windows 排程，只在 README 說明。
- 不做 P3 評分或個人化。

## Capabilities
### New Capabilities
- feedback-collect: R1～R5，收集與寫入、驗證與略過、按鈕狀態、失敗與重複處理、status 摘要。
### Modified Capabilities
- 無。telegram-push 的 callback data 與訊息格式不變；keyboard 新增可選的已選標記，推送時不使用。

## Impact
修改 notifier.py（getUpdates、editMessageReplyMarkup、共用 API 呼叫）、store.py（回饋寫入、推送對應、統計）、cli.py（collect 指令與 status）、README.md；新增 tests/test_feedback_collect.py 並登錄 workflow.config.json。

風險：未在 24 小時內執行 collect 的點擊會遺失，但使用者可以再按一次；處理到一半失敗時更新會重送，寫入必須可重複執行。
