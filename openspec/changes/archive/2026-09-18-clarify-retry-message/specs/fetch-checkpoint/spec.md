## MODIFIED Requirements

### Requirement: R4 - Actionable failure
未完成的 daily 指令 SHALL 回傳非零退出碼。錯誤 SHALL 說明起點保留、調高 max_results 後重跑、此次未完成查詢的起迄 UTC 時間（分鐘精度），以及系統不會自動調高上限。不得把上限中止描述為完整成功。

#### Scenario: Actionable failure acceptance
- **WHEN** 抓取超過上限
- **THEN** 退出碼為 1 且錯誤包含起點保留及重跑方法

#### Scenario: Operator can identify retry window
- **WHEN** 2026-09-01 00:00 至 2026-09-02 00:00 UTC 的查詢超過上限
- **THEN** 退出碼為 1，錯誤顯示上述 UTC 起訖時間、保留起點及調高 max_results 後重跑，並說明不會自動調高上限
