# arXiv Digest

每天自動從 [arXiv](https://arxiv.org/) 抓取指定領域的新論文，篩出可能感興趣的，推送標題與摘要。

延伸自 [AIPE 期中專案](../AIPE/Midterm_projuct) 的 arXiv 爬蟲。期中專案是一份已完成的作業（保持凍結），
這裡是把它長成一個實際每天在跑的工具，兩邊的程式碼與資料庫都各自獨立。

## 目前進度

| 階段 | 內容 | 狀態 |
|---|---|---|
| P0 | 專案骨架、資料庫 schema | ✅ 完成並驗證 |
| P1 | 每日自動抓取（增量、去重、限速、斷點續傳） | ✅ 完成並驗證 |
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

排程只要固定跑 `daily`。它從 `runs` 表裡「上次成功執行涵蓋到的時間點」接續，
**不是**寫死抓過去 24 小時 —— 所以筆電關機三天再開，中間的論文一樣補得回來。

### 設定 Windows 排程

工作排程器 → 建立基本工作 → 每日：

| 欄位 | 值 |
|---|---|
| 程式或指令碼 | `<LOCAL_PATH>` |
| 新增引數 | `-m arxiv_digest daily` |
| 開始位置 | `<PROJECT_ROOT>` |

「開始位置」不能省略，否則找不到 `config.ini`。

「程式或指令碼」填的是實際要用的 Python 路徑：直接用全域 Python 就是上表那個，
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
