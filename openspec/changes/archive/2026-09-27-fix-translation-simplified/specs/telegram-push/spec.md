## ADDED Requirements

### Requirement: R9 - Traditional Chinese normalization
翻譯成功後、組成訊息前，系統 SHALL 對 title_zh 與 summary_zh 進行正規化：不屬於 Big5 常用字（A440～C67E 區段）的漢字，若 OpenCC s2tw 可將其轉為常用字，SHALL 替換為轉換結果；Big5 常用字 SHALL 不被改動。接著 SHALL 依固定對照表替換下列大陸用語：視頻→影片、音頻→音訊、實時→即時、代碼→程式碼、信號→訊號、信息→資訊、網絡→網路、數據集→資料集、魯棒性→穩健性、算法→演算法（已是「演算法」時不重複替換）。英文內容與未翻譯的訊息 SHALL 不受影響。

#### Scenario: Simplified characters fixed
- **WHEN** 模型回傳「该方法这个数据的情况」
- **THEN** 訊息中為「該方法這個數據的情況」

#### Scenario: Valid Traditional text untouched
- **WHEN** 模型回傳「干擾、證明了、台灣、文件與參數、更多任務、演算法」
- **THEN** 訊息中的內容完全相同

#### Scenario: Mainland terms replaced
- **WHEN** 模型回傳「以算法處理視頻與實時信號」
- **THEN** 訊息中為「以演算法處理影片與即時訊號」
