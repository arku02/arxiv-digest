# arXiv Digest

從 [arXiv](https://arxiv.org/) 抓取指定領域的新論文並存入 MySQL。目前完成抓取、去重與失敗續抓；推送、回饋收集及 LLM 興趣評分仍待開發。

延伸自 AIPE 期中專案的 arXiv 爬蟲。期中專案是一份已完成的作業（保持凍結），
這裡是把它長成一個實際每天在跑的工具，兩邊的程式碼與資料庫都各自獨立。

## 目前進度

| 階段 | 內容 | 狀態 |
|---|---|---|
| P0 | 專案骨架、資料庫 schema | 已實作 |
| P1 | 每日抓取（增量、去重、限速、斷點續傳、公告延遲回看） | 已實作；22 項離線測試，驗證邊界見下方 |
| P2 | 推送管線 + 回饋收集 | ⬜ 未開始 |
| P3 | LLM 興趣評分，只推 top N | ⬜ 未開始 |
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
categories = cs.CV, cs.CL
```

分類語法沿用 arXiv API，例如 `cs.CV`（電腦視覺）、`cs.CL`（計算語言學）、`cs.LG`（機器學習）。

訂閱量會直接影響之後 P3 的 API 花費。實測 `cs.CV` + `cs.CL` 的每日論文量（2026/08/31–09/08）：

| 一 | 二 | 三 | 四 | 五 | 六 | 日 |
|---|---|---|---|---|---|---|
| 317 | 287 | 221 | 222 | 160 | 86 | 100 |

平均約 **194 篇/天**，週末明顯少、週一最多。估算成本時用平均值，別用高峰值。

## 使用

```bash
python -m arxiv_digest init-db            # 建立資料庫與資料表
python -m arxiv_digest daily              # 抓取上次執行至今的新論文
python -m arxiv_digest backfill --days 7  # 回頭補抓過去 7 天
python -m arxiv_digest status             # 看最近的執行紀錄
```

排程只要固定跑 `daily`。它從 `runs` 表裡「上次成功執行涵蓋到的時間點」往前 `lookback_days` 天（預設 4）接續，
若有尚未被後續完整成功涵蓋的失敗／執行中區間，也會保留其中最早起點（沿用原起點，不再往前回看）。只有完全沒有歷史紀錄時，才依 initial_backfill_days 回溯。

### 公告延遲回看

arXiv API 要等論文公告後才查得到。平日約 14:00 ET 截止、20:00 ET 公告；週五截止後的投稿要到週一晚上才公告，最長約 3 天多，公告後 API 索引還會再慢一點。
只查「上次到現在」的話，排程執行時尚未公告的論文會被當成沒有，之後也不會再查。2026-09-18～09-21 的缺口就是這樣造成的。

因此 `daily` 每次重查前 `lookback_days` 天。重疊的論文靠 `arxiv_id` 去重，`status` 的「取回」會明顯大於「新增」，這是正常的。
每次約查 5 天、平日約 800～1300 筆、10 多次請求（約 40 秒），`max_results` 請至少設 1500，範例為 2000。

假日停刊超過 `lookback_days` 時仍可能漏抓，需要手動補抓。已漏掉的舊資料也不會自動補回，例如：

```bash
python -m arxiv_digest backfill --days 10
```

`backfill` 以指定天數為起點，不另加回看；範圍大時記得暫時調高 `max_results`（10 天約需 2500）。

### 抓取上限與重試

達到 max_results 後，程式會沿用相同查詢額外探查最多一筆：沒有剩餘則正常完成；仍有資料則回報失敗，這批部分資料不入庫，續抓起點保留。請調高 max_results 後重跑 daily；上限不變可能持續失敗，本版不會自動增加流量或拆分區間。

探查請求沿用限速與重試；若探查失敗也不標記成功。max_results 限制交付資料筆數，額外探查的一筆不入庫。第一次抓取失敗後，隔天重跑仍沿用保存的起點。

上限錯誤會顯示此次查詢的 UTC 起訖時間（分鐘精度），並明確說明系統不會自動調高上限，方便判斷重試範圍。

此修正不會自動找回以前已被誤標 success 的漏抓資料；需要另外指定 backfill 範圍。仍假設單一排程，沒有索引快照或所有資料庫寫入錯誤的完整性保證。

### 離線驗證與變更流程

本專案使用 [整合工作流程](WORKFLOW-GUIDE.md)，規則見 [PROJECT-RULES.md](PROJECT-RULES.md)。OpenSpec 管理規格；Python unittest 驗證功能。

```text
npm ci --ignore-scripts --no-audit --no-fund
npm test
npm run workflow -- new <change-name>
```

workflow.config.json 的 pythonExecutable 指向實際 Python；移到其他電腦時需要調整。Python 套件另依 requirements.txt 安裝。
測試使用模擬 Atom 回應及記憶體資料庫，不讀取 config.ini，不連線 arXiv／MySQL／Telegram；其中 SQLite 只驗證查詢邏輯，不代表真實 MySQL 驗證。

### 設定 Windows 排程

工作排程器 → 建立基本工作 → 每日：

| 欄位 | 值 |
|---|---|
| 程式或指令碼 | `<實際 Python 執行檔完整路徑>` |
| 新增引數 | `-m arxiv_digest daily` |
| 開始位置 | `<arxiv-digest 專案根目錄>` |

「開始位置」不能省略，否則找不到 `config.ini`。

「程式或指令碼」填的是實際要用的 Python 路徑：請填入本機實際路徑，
若改用虛擬環境則換成 `<專案目錄>\.venv\Scripts\python.exe`。
用 `python -c "import sys; print(sys.executable)"` 可以查到目前用的是哪一個。

## 資料庫結構

`init-db`（以及每次 `daily`）會自動建立下列五張表：

| 資料表 | 用途 | 備註 |
|---|---|---|
| `papers` | 論文主表 | `arxiv_id` UNIQUE，**不含版本號** |
| `authors` | 作者表 | `paper_id` FK → papers.id，一對多 |
| `scores` | LLM 評分結果 | P3 開始使用 |
| `feedback` | 你的「有興趣 / 沒興趣」 | 未來個人化模型的訓練資料 |
| `runs` | 每次執行涵蓋的時間區間 | 斷點續傳靠這張表 |

去重用 `arxiv_id` 而不是網址，是因為論文從 `v1` 改版到 `v2` 時網址會變，
用網址當唯一鍵會讓同一篇論文重複入庫。

## 開發工具與歷史資料

`scripts/`、`openspec/`、`tests/`、`package.json` 與 `workflow.config.json` 已是本專案的開發及驗證工具，需要保留。現行入口為第一版平面流程，不需要重新套用公開模板。

`.workflow/baselines/`、`evidence/`、`receipts/` 保存歷史基準、驗證輸出及封存回條。試驗副本路徑屬於當時紀錄，不能解讀為原專案最近一次測試結果。

試驗過程檔已另行封存；本次整理及新的離線驗證見 [整理紀錄](docs/MAINTENANCE-2026-09-27.md)。原專案尚未加入模板隔離副本中的 `preview` 指令。

## 專案結構

```
arxiv_digest/
├── config.py     設定讀取
├── fetcher.py    arXiv API：增量查詢、分頁、限速、重試
├── store.py      MySQL：建表、去重寫入、執行紀錄
└── cli.py        命令列進入點
```

`scorer.py`（LLM 評分）與 `notifier.py`（推送）等 P2/P3 開始時再建，
現在不放空檔案佔位。

## 備註

arXiv 官方要求 API 請求之間至少間隔 3 秒，設定檔的 `request_delay` 不建議調低。
