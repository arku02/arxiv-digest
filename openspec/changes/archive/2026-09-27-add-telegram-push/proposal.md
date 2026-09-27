# Telegram 每日推送

## Why
P1 已每天存入約 194 篇論文，但沒有讀取介面，也沒有使用者回饋。P3 的 LLM 評分需要一組無篩選偏差的標註資料才能衡量準確度，推送管道同時是標註介面。

成功標準：每天在 Telegram 收到固定篇數、隨機抽樣的新論文，每篇附三個回饋按鈕；抽樣紀錄足以在之後還原每篇被抽中的機率。

使用者決定（2026-09-27）：每天 10 篇；按鈕三種 👎 沒興趣／👍 有興趣／⭐ 超想讀；回饋由之後的變更以每小時排程收集。

## What Changes
- 新增 push 指令：從上次成功推送後新入庫、且未推送過的論文中，均勻隨機抽 daily_limit 篇（預設 10），每篇一則 Telegram 訊息。
- 訊息含標題、作者、分類、摘要節錄、arXiv 連結，下方三個按鈕的 callback data 固定為 fb:<paper_id>:<0|1|2>，供 add-feedback-collect 使用。
- 新增 push_batches、pushes 兩張表，記錄每批的候選數與每篇對應的 Telegram 訊息。
- push --dry-run：印出將推送的內容，不發送、不寫入，不需要 bot token。
- Telegram 設定只在 push 時檢查；token 不出現在任何輸出。
- 採 full：新增外部介面（Telegram Bot API）、資料表與排程步驟。

## Non-goals
- 不收集按鈕回饋、不寫 feedback 表、不改 status 顯示；這些屬於 add-feedback-collect。
- 不做 LLM 評分、摘要翻譯或關鍵字篩選。
- 不建立或修改 Windows 排程、不代填 bot token；只在 README 說明。
- 部分推送失敗時不撤回已送出的訊息。

## Capabilities
### New Capabilities
- telegram-push: R1～R5，抽樣、訊息格式、推送紀錄與失敗、設定與機密、預覽模式。
### Modified Capabilities
- 無。fetch-checkpoint 行為不變。

## Impact
新增 arxiv_digest/notifier.py；修改 config.py、store.py（兩張新表與查詢）、cli.py（push 指令）、config.ini.example、README.md；新增 tests/test_telegram_push.py 並登錄 workflow.config.json。

風險：Telegram API 錯誤訊息或網址可能含 bot token，須遮蔽；推送到一半失敗會造成當天少於 10 篇、隔天補上。
