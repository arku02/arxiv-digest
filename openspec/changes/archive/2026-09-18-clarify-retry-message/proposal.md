# 明確指出重試區間

## Why
操作者需要從錯誤文字辨認哪段 UTC 時間尚未完成，並知道系統不會自動放寬上限。

## What Changes
僅擴充上限錯誤的說明，保留既有中止／重試行為。同時補足首輪同步後發現過短的正式規格 Purpose。

## Capabilities
### Modified Capabilities
- fetch-checkpoint: R4 錯誤文字。

## Impact
fetcher.py、tests/test_fetch_checkpoint.py、README.md；lite。
