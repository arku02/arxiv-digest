"""回饋備份：把推送與回饋紀錄匯出成 CSV，提交並推送到私人 git repo。

論文本身可以用 arxiv_id 從 arXiv 重抓，但「推了哪些、使用者怎麼標」無法重建，
所以只備份這部分。每次整份重寫並固定排序，資料沒變時檔案位元組相同，
git 就不會有差異，也不會產生空提交。
"""

from __future__ import annotations

import csv
import io
import logging
import subprocess
from datetime import date, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

BACKUP_FILE = "pushes.csv"

COLUMNS = (
    "arxiv_id", "title", "categories", "published", "batch_id", "pool_size", "batch_sent",
    "pushed_at", "label", "label_name", "feedback_at",
)

LABEL_NAMES = {0: "沒興趣", 1: "有興趣", 2: "超想讀"}


class BackupError(RuntimeError):
    """備份資料夾或 git 操作失敗。"""


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def render_csv(rows: list[dict]) -> bytes:
    """組出 pushes.csv 的內容。含 BOM，Excel 直接開啟中文才不會亂碼。"""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(COLUMNS)
    for row in rows:
        label = row["label"]
        values = dict(row, label_name=LABEL_NAMES.get(label, "") if label is not None else "")
        writer.writerow(_text(values[column]) for column in COLUMNS)
    return buffer.getvalue().encode("utf-8-sig")


def _git(directory: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=directory, capture_output=True, text=True, encoding="utf-8",
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise BackupError(f"git {args[0]} 失敗：{detail}")
    return result.stdout


def check_repository(directory: Path) -> None:
    """備份資料夾必須是既有的 git 工作目錄。在連線資料庫前檢查。"""
    if not (directory / ".git").exists():
        raise BackupError(
            f"備份資料夾 {directory} 不存在或不是 git 工作目錄；"
            "請先 clone 私人 repo，或在 config.ini 的 [BACKUP] dir 指定位置"
        )


def save_and_commit(directory: Path, rows: list[dict], push: bool) -> bool:
    """寫入 pushes.csv，有變動才提交；push 為 True 時每次都推送。

    Returns:
        是否建立了新提交。
    """
    (directory / BACKUP_FILE).write_bytes(render_csv(rows))

    committed = False
    if _git(directory, "status", "--porcelain", "--", BACKUP_FILE).strip():
        answered = sum(1 for row in rows if row["label"] is not None)
        _git(directory, "add", "--", BACKUP_FILE)
        _git(directory, "commit", "-q", "-m", f"backup: 推送 {len(rows)} 篇、回饋 {answered} 篇",
             "--", BACKUP_FILE)
        committed = True
        logger.info("已提交備份：推送 %d 篇、回饋 %d 篇", len(rows), answered)
    else:
        logger.info("資料沒有變動，不建立提交")

    if push:
        # 每次都推：上次推送失敗留在本機的提交，這次一起補上
        _git(directory, "push", "-q", "origin", "HEAD")
        logger.info("已推送到遠端")
    return committed
