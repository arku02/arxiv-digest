# 專案工作規則

本專案為 Python arxiv-digest，使用 python-unittest。預設離線測試只用模擬資料，不讀取 config.ini、不連線 API/MySQL/Telegram。移機時調整 workflow.config.json 的 pythonExecutable。

- 先讀 README.md、workflow.config.json 及本次變更；現行規格在 openspec/specs，待實作需求在 openspec/changes。
- 提案寫產品目的；規格寫外部行為；設計寫擬採方案；架構文件只寫有程式證據的現況；重要取捨留下 ADR。
- 文件使用繁體中文；OpenSpec 必要標題及 SHALL/MUST 語法維持工具格式。
- 需求以 R1、R2 等穩定編號表示；技術檢查以 D1 等表示；每個變更內編號不可重複。
- Node 測試名稱用 `R1: 情境` 或 `D1: 情境`；Python unittest 方法用 `test_R1_情境` 或 `test_D1_情境`，讓 verify 能核對案例確實執行。
- 建立變更使用 npm run workflow -- new <name>，先讀工具產生的規格基準，不手建無基準變更。
- 實作前使用 check。review 只有在實際審查後才能 ready；待決業務問題寫入 openQuestions，不能自行假設為已同意。
- 一個變更只有一份 tasks.md；不要另外建立 PLAN.md 或另一套工具的任務狀態。
- 完成實作後依序執行 verify、archive。測試沒跑、失敗、跳過或證據過期，都不能宣告完成。
- 上游改變後重新檢查；現行規格改動時使用 rebase 並重新審查，不直接改 baseline JSON 以消除阻擋。
- 不使用原生 archive 繞過驗證，不以修改測試預期掩蓋程式違反有效規格。
- 正式系統的技術棧、資料與外部操作權限需在目標專案確認；依 testRunner 選擇 Node 或 Python unittest，不假造其他設定。

- 純文件與檔案整理不虛構功能 delta；本版本不支援純文件 OpenSpec 變更，改以 Git 保存並執行既有離線測試，另記錄整理結果。不得重寫歷史封存證據。
