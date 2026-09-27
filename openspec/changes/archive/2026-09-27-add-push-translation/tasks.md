# 任務

## 1. 實作與驗證
- [x] 1.1 format_message 支援翻譯格式，未翻譯時輸出不變；來源 R2；驗證 tests/test_push_translation.py
- [x] 1.2 OllamaTranslator 呼叫 /api/chat 並解析 JSON，push 與 dry-run 套用；來源 R6；驗證 tests/test_push_translation.py
- [x] 1.3 翻譯失敗退回英文並停止本批其餘翻譯；來源 R7；驗證 tests/test_push_translation.py
- [x] 1.4 TranslateConfig 延後驗證與預設值；來源 R8；驗證 tests/test_push_translation.py
- [x] 1.5 新測試檔登錄並維持離線隔離；來源 D1；驗證 tests/test_push_translation.py
- [x] 1.6 更新 config.ini.example 與 README 的翻譯設定、Ollama 說明與耗時；來源 R8；驗證 tests/test_push_translation.py
