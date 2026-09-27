# 技術設計

## 已知事實
來源 commit 27c5ef468aee8603e1787d21ff31a372fac36e63；config.ini.example 的 Telegram 區塊為使用者既有未提交改動。
fetcher 只回傳 list；cli 無條件完成 success；runs 已保存起迄點及 running/failed/success，不需新增表。

## 方案與取捨
保留 list 回傳型別，新增 FetchLimitExceeded。達上限才追加一筆探查，沿用 _request 的限速／重試；超量在 save_papers 前中止。
此版保留整段重試，不持久化 offset，不自動擴大流量。操作者需提高 max_results 再跑；上限不變會再次失敗。
Store.next_fetch_start 使用 NOT EXISTS 找出尚未被較晚成功完整覆蓋的失敗／執行中區間，與最新成功終點取最早。
只處理本次上限造成的漏抓；既有 save_papers 吞掉部分寫入錯誤、API 索引變動、並行工作與歷史誤標 success 是另案。

## 假設與邊界
單一排程執行者、API 回應能由既有解析器正確解讀。探查空結果只反映當次回應，不代表 arXiv 快照交易。
不讀取 config.ini、不連真實 API/MySQL；requests/pymysql 入口在測試中禁止使用。

## 驗證與回復
Python unittest；固定時鐘、Atom 模擬回應，真實 fetcher/cli 邏輯及 SQLite 執行讀取 SQL。SQLite 驗證查詢邏輯，不代表 MySQL 實機驗證。
Python runner 記錄實際案例，拒絕零測試、失敗、skip、expectedFailure、缺需求 ID。
此修正不變更資料 schema；還原程式會恢復原有風險，勿清除 runs 來掩蓋未完成區間。

## 文件影響
README 補充上限與重試說明；PROJECT-RULES 及 WORKFLOW-GUIDE 描述 Python 入口；正式規格只在 archive 後同步。
