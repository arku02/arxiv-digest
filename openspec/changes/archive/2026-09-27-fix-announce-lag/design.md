# 技術設計

## 已知事實
- 來源 commit 30036e03f8d8277aa20745422b2affa06bf182ca；基準規格為 openspec/specs/fetch-checkpoint/spec.md（R1～R4）。
- cli.run_fetch：until 為現在時間；since 為 store.next_fetch_start()，無歷史時為 until 減 initial_backfill_days；backfill 直接傳入 since。
- Store.next_fetch_start 回傳 min(最新成功終點, 未被覆蓋的 failed/running 起點)。runs 保存每次實際查詢的 window_start／window_end。
- fetcher 以 submittedDate:[since TO until] 查詢；API 回傳空結果時 run_fetch 標記 success。
- 本機資料庫的缺口與推論見 proposal.md；arXiv 公告延遲為依官方公告時程與資料的推論，未以即時 API 驗證。

## 假設與待決問題
- 假設正常情況下論文從提交到 API 查得到最長約 3 天 6 小時加數小時索引延遲；預設 4 天約留 18 小時餘裕。假日停刊更久時仍可能漏抓，需另跑 backfill。
- 假設排程至少每 lookback_days 天內會有一次 daily；筆電關機更久時，起點仍由最新成功終點往前回看，不會漏掉先前未公告的論文。
- 無待決業務問題。本機 config.ini 的 max_results 屬操作者設定，本變更不修改，於交付時提醒。

## 擬採方案與取捨
- ArxivConfig 新增 lookback_days: int = 4，__post_init__ 拒絕非 int（含 bool）或負數；load_config 以 getint 讀取，fallback 4。放在 dataclass 驗證，直接建構與讀檔兩條路徑都在連線前失敗。
- Store.next_fetch_start(lookback=timedelta(0))：成功終點先減 lookback 再與 failed/running 起點取最早值。預設參數為 0，舊呼叫行為不變。
- 失敗區間起點不再減 lookback：失敗那次的起點已包含當時的回看。若再疊加，連續失敗會每次往前 4 天，查詢量越滾越大並反覆觸發 R2 上限失敗。
- 首次回溯及 backfill 不加 lookback：前者下一次 daily 會回看補上，後者是操作者明確指定的範圍。
- 替代方案：區間終點延後（until = now − N）會讓新論文晚 N 天才入庫，不利之後的每日推送；改用 OAI-PMH 依公告日期查詢較精確，但需換抓取介面，改動過大。
- 代價：每次查詢約 5 天，多數是重複論文，由 arxiv_id 去重；runs.fetched 會大於 new_count。

## 架構與資料影響
不變更資料表。runs.window_start 記錄含回看的實際查詢起點，舊紀錄不需遷移。config.ini 未設定 lookback_days 時採預設 4；config.ini.example 新增此欄並將 max_results 調為 2000。

### Check: D1 - Offline isolation
新增測試沿用 requests／pymysql 禁用 patch；設定驗證只讀暫存檔，不讀 config.ini、不連線。

## 驗證與回復
- Python unittest 於 tests/test_fetch_checkpoint.py 新增 R3、R5、D1 案例：以模擬 API 依「現在時間」決定論文是否已公告，重現週五提交、週一公告的情境；同一情境 lookback_days=0 時論文漏抓，作為對照。
- 先在未修正程式上執行新測試並確認失敗，再實作。SQLite 只驗證查詢邏輯，不代表 MySQL 實機驗證。
- 回復：還原程式即恢復原行為，runs 紀錄仍相容；或在 config.ini 設 lookback_days = 0。
