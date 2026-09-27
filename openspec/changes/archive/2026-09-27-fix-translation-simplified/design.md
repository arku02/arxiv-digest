# 技術設計

## 已知事實
- 來源 commit 3fccf34。translator.OllamaTranslator.translate 回傳 Translation(title_zh, summary_zh)，已合併空白；format_message 負責跳脫與截斷。
- 本機已安裝 opencc 1.4.2（PyPI 官方 wheel，cp313 win_amd64），提供 OpenCC('s2tw').convert。
- 對既有 44 段翻譯的比對（見 proposal）：s2twp 有大量詞彙誤改；s2tw 會把「證明了」改成「證明瞭」、「干擾」改成「幹擾」；s2t 會把「群」改成「羣」。
- cp950 編碼中，Big5 常用字位於 0xA440～0xC67E（5401 字）。「与」「据」「优」雖可用 cp950 編碼，但位於次常用字區；「干」「了」「台」「后」位於常用字區。

## 假設與待決問題
- 假設台灣繁體中文的正常文字幾乎只用常用字；次常用字區的正體字（例如「脣」「樑」）若被 s2tw 轉成常用異體字（唇、梁），意思不變，可以接受。
- 無待決業務問題。

## 擬採方案與取捨
- 逐字處理：只有非常用字才查 s2tw 單字轉換，且結果必須是常用字才替換。避免 OpenCC 詞組規則在已是繁體的文字上誤判，也保證常用字零改動。
- 代價：本身也是常用字的簡體字（后、干、台、里等）不會被修正；這些字在繁體文字中有正確用法，無法只看單字判斷。
- 用語對照只收錄在台灣沒有其他常見意思的詞；「算法」以負向回顧（前面不是「演」）避免變成「演演算法」。
- OpenCC 轉換器於第一次使用時建立並重複使用。
- 正規化放在 translate 回傳前，dry-run 與 push 共用，format_message 不需變動。
- 替代方案：在提示詞加強要求（已做過，仍有漏網）；改用更大的模型（CPU 速度不允許）。

## 架構與資料影響
requirements.txt 新增 opencc==1.4.2。不影響資料表、設定與訊息格式。

### Check: D2 - Dependency pinned
requirements.txt 固定 opencc==1.4.2，translator 模組可匯入 opencc。

## 驗證與回復
- Python unittest：test_R9_* 以模擬 Ollama 回傳含簡體字、正確繁體字與大陸用語的內容，驗證推送訊息；test_D2_* 驗證依賴固定。既有 65 項測試須全數通過。
- 實機確認：以 push --dry-run 確認後封存。
- 回復：還原 translator.py 即可；不影響資料。
