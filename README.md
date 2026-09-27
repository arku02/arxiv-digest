# arXiv Digest

從 [arXiv](https://arxiv.org/) 抓取指定領域的新論文並存入 MySQL，每天隨機推送 10 篇到 Telegram（可用本機模型翻成繁體中文），並收集你按的回饋。依回饋挑選論文的評分功能（P3）仍待開發。

延伸自 AIPE 期中專案的 arXiv 爬蟲。期中專案是一份已完成的作業（保持凍結），
這裡是把它長成一個實際每天在跑的工具，兩邊的程式碼與資料庫都各自獨立。

## 目前進度

| 階段 | 內容 | 狀態 |
|---|---|---|
| P0 | 專案骨架、資料庫 schema | 已實作 |
| P1 | 每日抓取（增量、去重、限速、斷點續傳、公告延遲回看） | 已實作；22 項離線測試，驗證邊界見下方 |
| P2 | 推送管線 + 回饋收集 | 已實作（含本機中文翻譯）；推送 16 項、收集 15 項、翻譯 17 項離線測試 |
| P3 | 興趣評分，只推 top N（LLM 或依回饋的向量相似度，方案待定） | ⬜ 未開始 |
| P4 | 向量粗篩降低成本、用回饋資料做個人化 | ⬜ 未開始 |

刻意讓 P2（推送）排在 P3（智慧篩選）前面：**推送管道同時是標註介面**，
沒有先累積你的回饋資料，就沒辦法衡量篩選到底準不準。

## 安裝

需要 Python 3.12 以上與 MySQL 8.0 以上。

```bash
pip install -r requirements.txt
```

想跟其他專案隔離的話，可以先建虛擬環境再安裝（非必要）：

```bash
python -m venv .venv
.venv\Scripts\activate
```

用了虛擬環境的話，記得排程設定的 Python 路徑也要跟著換，見下方。

## 設定

```bash
cp config.ini.example config.ini
```

`config.ini` 不進版控（已在 `.gitignore`）。要填的是資料庫帳密與訂閱的分類：

```ini
[ARXIV]
categories = cs.AI, cs.CL, cs.CV
```

分類語法沿用 arXiv API，例如 `cs.AI`（人工智慧：Agent、推理、規劃）、`cs.CL`（計算語言學，多數 LLM 論文在這裡）、`cs.CV`（電腦視覺）、`cs.LG`（機器學習）。
注意 arXiv 的 `cs.AI` 不含視覺、機器學習、NLP 與機器人，這些各有獨立分類。

訂閱量會影響 daily 的查詢量、推送的候選篇數，以及之後 P3 評分的運算量。實測一週（2026/09/14–09/20）的每日平均：

| 分類 | 每日篇數 |
|---|---|
| `cs.AI` | 148 |
| `cs.LG` | 140 |
| `cs.CV` | 92 |
| `cs.RO` | 85 |
| `cs.CL` | 71 |
| **`cs.AI` + `cs.CL` + `cs.CV`（目前訂閱）** | **263** |

一篇論文常同時掛好幾個分類，組合後的篇數會小於各分類相加。週末明顯少、週一最多；舊的 `cs.CV` + `cs.CL` 實測（2026/08/31–09/08）平均 194 篇/天，週一 317、週六 86。

## 使用

```bash
python -m arxiv_digest init-db            # 建立資料庫與資料表
python -m arxiv_digest daily              # 抓取上次執行至今的新論文
python -m arxiv_digest backfill --days 7  # 回頭補抓過去 7 天
python -m arxiv_digest status             # 看最近的執行紀錄
python -m arxiv_digest push --dry-run     # 預覽今天要推送的論文，不發送
python -m arxiv_digest push               # 推送到 Telegram
python -m arxiv_digest collect            # 收集按鈕回饋
```

排程只要固定跑 `daily`。它從 `runs` 表裡「上次成功執行涵蓋到的時間點」往前 `lookback_days` 天（預設 4）接續，
若有尚未被後續完整成功涵蓋的失敗／執行中區間，也會保留其中最早起點（沿用原起點，不再往前回看）。只有完全沒有歷史紀錄時，才依 initial_backfill_days 回溯。

### 公告延遲回看

arXiv API 要等論文公告後才查得到。平日約 14:00 ET 截止、20:00 ET 公告；週五截止後的投稿要到週一晚上才公告，最長約 3 天多，公告後 API 索引還會再慢一點。
只查「上次到現在」的話，排程執行時尚未公告的論文會被當成沒有，之後也不會再查。2026-09-18～09-21 的缺口就是這樣造成的。

因此 `daily` 每次重查前 `lookback_days` 天。重疊的論文靠 `arxiv_id` 去重，`status` 的「取回」會明顯大於「新增」，這是正常的。
訂閱 3 個分類時，每次約查 5 天、約 1300～1500 筆、10 多次請求（約 1 分鐘），`max_results` 請至少設 2000，範例為 3000。

假日停刊超過 `lookback_days` 時仍可能漏抓，需要手動補抓。已漏掉的舊資料也不會自動補回，例如：

```bash
python -m arxiv_digest backfill --days 10
```

`backfill` 以指定天數為起點，不另加回看；範圍大時記得暫時調高 `max_results`（3 個分類 10 天約 3000 篇，建議暫時調到 4000）。

### 抓取上限與重試

達到 max_results 後，程式會沿用相同查詢額外探查最多一筆：沒有剩餘則正常完成；仍有資料則回報失敗，這批部分資料不入庫，續抓起點保留。請調高 max_results 後重跑 daily；上限不變可能持續失敗，本版不會自動增加流量或拆分區間。

探查請求沿用限速與重試；若探查失敗也不標記成功。max_results 限制交付資料筆數，額外探查的一筆不入庫。第一次抓取失敗後，隔天重跑仍沿用保存的起點。

上限錯誤會顯示此次查詢的 UTC 起訖時間（分鐘精度），並明確說明系統不會自動調高上限，方便判斷重試範圍。

此修正不會自動找回以前已被誤標 success 的漏抓資料；需要另外指定 backfill 範圍。仍假設單一排程，沒有索引快照或所有資料庫寫入錯誤的完整性保證。

### Telegram 推送

`push` 從「上次成功推送之後新入庫、而且沒推過」的論文中，隨機抽 `daily_limit` 篇（預設 10），每篇發一則訊息，附 👎 沒興趣／👍 有興趣／⭐ 超想讀 三個按鈕。第一次推送的候選是過去 24 小時入庫的論文。

刻意用隨機抽樣而不是挑選：P3 要拿這些回饋評估評分準不準，先篩過的資料會帶偏差。每批的候選篇數記在 `push_batches.pool_size`，之後可以還原每篇被抽中的機率。

設定步驟：

1. 在 Telegram 對 @BotFather 輸入 `/newbot`，取得 bot token
2. 對 @userinfobot 傳任意訊息，取得自己的數字 ID
3. 對自己的新 bot 按 Start（沒按會收到 403）
4. 填入 `config.ini` 的 `[TELEGRAM]`，先跑 `push --dry-run` 看內容，再跑 `push`

推送到一半失敗時，已送出的會保留，本批記為失敗，下次 `push` 從剩下的候選重新抽。錯誤訊息會把 bot token 換成 `<bot_token>`。

### 中文翻譯

在 `config.ini` 的 `[TRANSLATE]` 設 `enabled = true` 後，`push` 與 `push --dry-run` 會先用本機 Ollama 把抽中的論文翻成台灣用語的繁體中文，訊息變成：粗體中文標題、英文原標題、作者、分類、完整中文摘要、連結。

- 完全在本機執行、免費，論文內容不會送到雲端服務
- 需要先安裝 [Ollama](https://ollama.com/) 並下載模型：`ollama pull qwen3.5:9b`（6.6 GB）
- 用 CPU 跑，每篇約 45～65 秒，10 篇約 10 分鐘（2026-09-27 實測推送 10 篇 10.5 分鐘）；執行時約佔 7～8 GB 記憶體，推送結束約 1 分鐘後釋放
- 翻譯失敗或 Ollama 沒在執行時，該篇改推英文，本批其餘論文也直接推英文，不會漏推
- 冷門術語可能翻得生硬；模型被要求沒把握的術語保留英文原文
- 翻譯後會自動修正混入的簡體字（只改台灣常用字以外的字，常用字一律不動），並把「視頻」「算法」等少數確定的大陸用語換成台灣用語；「優化」「支持」這類台灣也用的詞不改
- 想暫停翻譯，把 `enabled` 改成 `false` 即可

選 `qwen3.5:9b` 的原因：2026-09-27 以同 3 篇論文比較，4b 每篇約 25 秒但有誤譯（如 distillation 譯成「精簡」），9b 加台灣用語對照後誤譯明顯減少。

### 收集回饋

`collect` 讀取你按下的按鈕，存進 `feedback`（0=沒興趣、1=有興趣、2=超想讀），每篇一筆，改按其他按鈕以最後一次為準。
存好後訊息上的按鈕會在目前選擇前加 ✅，其他按鈕仍可改按。`status` 會顯示推送篇數、回饋篇數、回饋率與三種回饋的篇數。

- 按下按鈕後不會立刻有反應，按鈕會轉圈一下，等下一次 `collect` 執行後才出現 ✅
- Telegram 只保留 24 小時內還沒讀取的點擊，所以 `collect` 要每小時排程執行；超過 24 小時沒收到的點擊會遺失，再按一次即可
- 只接受來自 `chat_id` 本人、而且對得上推送紀錄的點擊，其他更新會略過
- 處理到一半失敗時不會向 Telegram 確認，下次會重送同一批，結果不變

### 離線驗證與變更流程

本專案使用 [整合工作流程](WORKFLOW-GUIDE.md)，規則見 [PROJECT-RULES.md](PROJECT-RULES.md)。OpenSpec 管理規格；Python unittest 驗證功能。

```text
npm ci --ignore-scripts --no-audit --no-fund
npm test
npm run workflow -- new <change-name>
```

workflow.config.json 的 pythonExecutable 指向實際 Python；移到其他電腦時需要調整。Python 套件另依 requirements.txt 安裝。
測試使用模擬 Atom 回應、模擬 Telegram 與 Ollama 回應及記憶體資料庫，不讀取 config.ini，不連線 arXiv／MySQL／Telegram／Ollama；其中 SQLite 只驗證查詢邏輯，不代表真實 MySQL 驗證，模擬回應也不代表真實翻譯品質。

### 設定 Windows 排程

工作排程器 → 建立基本工作 → 每日：

| 欄位 | 值 |
|---|---|
| 程式或指令碼 | `<實際 Python 執行檔完整路徑>` |
| 新增引數 | `-m arxiv_digest daily` |
| 開始位置 | `<arxiv-digest 專案根目錄>` |

「開始位置」不能省略，否則找不到 `config.ini`。

要推送的話，在同一個工作的「動作」頁再新增一個動作，程式與開始位置相同、引數填 `-m arxiv_digest push`。多個動作會依序執行，推送會在抓取之後；開啟翻譯時推送約需 10 分鐘。

arXiv 在美東時間 20:00 公告：美國夏令時間是台灣早上 8 點，11 月初夏令時間結束後變成 9 點。排程設在 **09:30**，全年都能讓當天新論文進候選。

筆電建議在兩個工作的內容中另外設定：

- 「條件」頁取消勾選「只有在電腦使用 AC 電源時才啟動工作」，沒插電也會執行
- 「設定」頁勾選「錯過排定的開始時間後，盡快執行工作」，關機錯過時開機後補跑

收集回饋另外用「建立工作」（不是「建立基本工作」）建一個：觸發程序選「每日」，進階設定勾選「重複工作間隔：1 小時」、「持續時間：不限制」，引數填 `-m arxiv_digest collect`，程式與開始位置同上。

「程式或指令碼」填的是實際要用的 Python 路徑：請填入本機實際路徑，
若改用虛擬環境則換成 `<專案目錄>\.venv\Scripts\python.exe`。
用 `python -c "import sys; print(sys.executable)"` 可以查到目前用的是哪一個。

## 資料庫結構

`init-db`（以及每個會連線資料庫的指令）會自動建立下列七張表：

| 資料表 | 用途 | 備註 |
|---|---|---|
| `papers` | 論文主表 | `arxiv_id` UNIQUE，**不含版本號** |
| `authors` | 作者表 | `paper_id` FK → papers.id，一對多 |
| `scores` | 評分結果 | P3 開始使用 |
| `feedback` | 你的回饋：0 沒興趣、1 有興趣、2 超想讀 | `paper_id` UNIQUE，改按以最後一次為準 |
| `runs` | 每次執行涵蓋的時間區間 | 斷點續傳靠這張表 |
| `push_batches` | 每次推送的批次 | 候選篇數、送出篇數、成功／失敗 |
| `pushes` | 每篇推送紀錄 | `paper_id` UNIQUE，保存 Telegram message_id |

去重用 `arxiv_id` 而不是網址，是因為論文從 `v1` 改版到 `v2` 時網址會變，
用網址當唯一鍵會讓同一篇論文重複入庫。

## 開發工具與歷史資料

`scripts/`、`openspec/`、`tests/`、`package.json` 與 `workflow.config.json` 已是本專案的開發及驗證工具，需要保留。現行入口為第一版平面流程，不需要重新套用公開模板。

`.workflow/baselines/`、`evidence/`、`receipts/` 保存歷史基準、驗證輸出及封存回條。試驗副本路徑屬於當時紀錄，不能解讀為原專案最近一次測試結果。

試驗過程檔已另行封存；當天早上的整理及離線驗證見 [整理紀錄](docs/MAINTENANCE-2026-09-27.md)，晚間的文件同步見 [文件同步紀錄](docs/MAINTENANCE-2026-09-27-docs-sync.md)。原專案尚未加入模板隔離副本中的 `preview` 指令。

## 專案結構

```
arxiv_digest/
├── config.py     設定讀取
├── fetcher.py    arXiv API：增量查詢、分頁、限速、重試
├── store.py      MySQL：建表、去重寫入、執行與推送紀錄
├── notifier.py   Telegram：訊息格式、回饋按鈕、推送與讀取更新
├── translator.py 本機 Ollama 翻譯與簡體字修正
└── cli.py        命令列進入點
```

`scorer.py`（P3 評分）等 P3 開始時再建，現在不放空檔案佔位。

## 備註

arXiv 官方要求 API 請求之間至少間隔 3 秒，設定檔的 `request_delay` 不建議調低。
