# 任務

## 1. 實作與驗證
- [x] 1.1 Store.backup_rows 與 pushes.csv 匯出（欄位、排序、標籤名稱、穩定輸出）；來源 R1；驗證 tests/test_data_backup.py
- [x] 1.2 backup 指令檢查 git 工作目錄、有變動才提交、每次推送、推送失敗回傳非零；來源 R2；驗證 tests/test_data_backup.py
- [x] 1.3 新增 [BACKUP] 設定與驗證，預設專案旁的 arxiv-digest-data；來源 R3；驗證 tests/test_data_backup.py
- [x] 1.4 新增測試維持離線隔離並登錄 workflow.config.json；來源 D1；驗證 tests/test_data_backup.py
- [x] 1.5 更新 config.ini.example、README 與開發手冊的備份與排程說明；來源 R3；驗證 tests/test_data_backup.py
