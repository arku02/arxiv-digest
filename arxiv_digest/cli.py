"""命令列進入點。

    python -m arxiv_digest init-db          建立資料庫與資料表
    python -m arxiv_digest daily            抓取上次執行至今的新論文
    python -m arxiv_digest backfill --days 7  回頭補抓過去 7 天
    python -m arxiv_digest status           看最近的執行紀錄
    python -m arxiv_digest push             推送今天的論文到 Telegram
    python -m arxiv_digest push --dry-run   只預覽，不發送
    python -m arxiv_digest collect          收集 Telegram 按鈕回饋，必要時補抓補推

排程只要固定跑 daily 就好。它會自己從「上次成功執行涵蓋到的時間點」接續，
所以筆電關機好幾天再開，中間的論文一樣補得回來。接續時會再往回重查
lookback_days 天，因為 arXiv 論文要公告後才查得到，上次執行時可能還看不到。

抓取失敗時 daily 用 Telegram 通知一次，push 暫停；每小時的 collect 會在
[RETRY] 時段內重抓，成功就補推，不必另外加排程。
"""

from __future__ import annotations

import argparse
import html
import logging
import random
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Callable

from arxiv_digest import notifier
from arxiv_digest.config import Config, load_config
from arxiv_digest.fetcher import LIMIT_ERROR_PREFIX, ArxivFetcher
from arxiv_digest.notifier import TelegramClient, format_message, keyboard
from arxiv_digest.store import Store
from arxiv_digest.translator import OllamaTranslator

logger = logging.getLogger("arxiv_digest")

# 最近一次抓取停在 running 超過這麼久，視為程序已中斷，補抓時重抓
RUNNING_STALE = timedelta(hours=1)


def utcnow() -> datetime:
    """現在時間（UTC，但去掉時區資訊）。

    MySQL 的 DATETIME 不存時區，讀回來一定是 naive。全程統一用 naive UTC，
    才不會出現「aware 與 naive 相減」的 TypeError。
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def localnow() -> datetime:
    """本機時間。補抓時段依使用者作息，用本機時間判斷。"""
    return datetime.now()


def run_fetch(config: Config, since: datetime | None = None) -> int:
    """執行一次抓取。since 留空則從上次成功的斷點接續。

    Returns:
        新增的論文筆數。
    """
    until = utcnow()

    with Store(config.db) as store:
        store.init_schema()

        if since is None:
            resume_start = store.next_fetch_start(
                timedelta(days=config.arxiv.lookback_days)
            )
            if resume_start is None:
                days = config.arxiv.initial_backfill_days
                since = until - timedelta(days=days)
                logger.info("首次執行，回溯 %d 天", days)
            else:
                since = resume_start
                logger.info(
                    "從上次斷點接續（含回看 %d 天）：%s",
                    config.arxiv.lookback_days, since,
                )

        gap = until - since
        logger.info(
            "查詢區間 %s ~ %s（共 %.1f 小時）",
            since, until, gap.total_seconds() / 3600,
        )

        run_id = store.start_run(since, until)

        try:
            fetcher = ArxivFetcher(config.arxiv)
            papers = fetcher.fetch(since, until)
            new_count, dup_count = store.save_papers(papers)

            store.finish_run(run_id, "success", fetched=len(papers), new_count=new_count)
            logger.info(
                "完成：取回 %d 筆，新增 %d 筆，略過重複 %d 筆（資料庫現有 %d 篇）",
                len(papers), new_count, dup_count, store.count_papers(),
            )
            return new_count

        except Exception as exc:
            # 標記失敗，下次執行才會把這段區間重抓一次
            store.finish_run(run_id, "failed", error=str(exc))
            logger.error("抓取失敗，這段區間會在下次執行時重抓：%s", exc)
            raise


def run_push(
    config: Config,
    dry_run: bool = False,
    rng: random.Random | None = None,
    sleep: Callable[[float], None] | None = None,
) -> int:
    """從上次成功推送後新入庫的論文隨機抽樣並推送。

    Returns:
        實際送出的篇數；預覽模式為 0。
    """
    # 設定錯誤要在連線資料庫前擋下；預覽不需要 token
    limit = config.telegram.limit()
    if not dry_run:
        token, chat_id = config.telegram.credentials()
    translate = config.translate.validated()
    rng = rng or random.Random()
    pause = sleep or time.sleep

    with Store(config.db) as store:
        store.init_schema()

        # 抓取失敗時候選池是空的，照推只會送出 0 篇又記成功；不建批次，下界就不會動
        latest = store.recent_runs(limit=1)
        if latest and latest[0]["status"] != "success":
            reason = f"最近一次抓取狀態為 {latest[0]['status']}，暫不推送；抓取成功後再推"
            if not dry_run:
                raise RuntimeError(reason)
            logger.warning("%s（預覽照常進行）", reason)

        started_at = store.db_now()
        after = store.last_success_push_start()
        if after is None:
            after = started_at - timedelta(days=1)
            logger.info("首次推送，候選為過去 24 小時入庫的論文")
        pool = store.push_pool(after, started_at)
        chosen = rng.sample(pool, min(limit, len(pool)))
        papers = store.papers_for_push(chosen)
        logger.info("候選 %d 篇，抽出 %d 篇", len(pool), len(papers))

        translator = OllamaTranslator(*translate) if translate else None

        def render(paper) -> str:
            # 翻譯失敗就改推英文；第一次失敗後本批不再翻譯，避免逐篇等逾時
            nonlocal translator
            translation = None
            if translator is not None:
                try:
                    translation = translator.translate(paper.title, paper.summary)
                except Exception as exc:
                    translator = None
                    logger.warning("翻譯失敗，本批其餘論文改推英文：%s", exc)
            return format_message(paper, translation)

        if dry_run:
            print(f"候選 {len(pool)} 篇，抽出 {len(papers)} 篇（預覽，未發送、未記錄）\n")
            buttons = " | ".join(text for text, _ in notifier.BUTTONS)
            for paper in papers:
                print(render(paper))
                print(f"[{buttons}]")
                print("-" * 40)
            return 0

        batch_id = store.start_push_batch(started_at, len(pool))
        client = TelegramClient(token, chat_id)
        sent = 0
        try:
            for index, paper in enumerate(papers):
                if index:
                    pause(notifier.SEND_INTERVAL)
                message_id = client.send(render(paper), keyboard(paper.id))
                store.record_push(batch_id, paper.id, chat_id, message_id)
                sent += 1
        except Exception as exc:
            # 已送出的保留；本批標記失敗，下次候選池仍從上次成功批次算起
            store.finish_push_batch(batch_id, "failed", sent, error=str(exc))
            logger.error("推送中斷，已送出 %d 篇，其餘下次再推：%s", sent, exc)
            raise

        store.finish_push_batch(batch_id, "success", sent)
        if not papers:
            logger.info("沒有新論文可推送")
        else:
            logger.info("推送完成：%d 篇", sent)
        return sent


# 推送按鈕的 callback data：fb:<paper_id>:<label>，label 0=沒興趣 1=有興趣 2=超想讀
_CALLBACK = re.compile(r"^fb:(\d+):([012])$")


def _feedback_from_update(update: dict, chat_id: str, store: Store) -> tuple[int, int, int] | None:
    """驗證一筆更新，有效時回傳 (paper_id, label, message_id)，否則 None。"""
    query = update.get("callback_query")
    if not query:
        return None
    message = query.get("message") or {}
    if str((message.get("chat") or {}).get("id")) != chat_id:
        return None
    match = _CALLBACK.match(query.get("data") or "")
    if not match or "message_id" not in message:
        return None
    paper_id, label = int(match.group(1)), int(match.group(2))
    # 要對得上我們推過的那則訊息，防止偽造或對錯論文
    if store.pushed_paper_for_message(chat_id, message["message_id"]) != paper_id:
        return None
    return paper_id, label, message["message_id"]


def run_collect(config: Config) -> dict:
    """讀取按鈕點擊並寫入回饋。

    每批處理完，下一次 getUpdates 帶新的 offset 才算確認；中途失敗就不再呼叫，
    未確認的更新下次會重送，寫入可重複執行所以結果不變。
    """
    token, chat_id = config.telegram.credentials()
    counts = {"saved": 0, "ignored": 0}

    with Store(config.db) as store:
        store.init_schema()
        client = TelegramClient(token, chat_id)
        offset = None
        while True:
            updates = client.get_updates(offset)
            if not updates:
                break
            for update in updates:
                found = _feedback_from_update(update, chat_id, store)
                if found is None:
                    counts["ignored"] += 1
                    continue
                paper_id, label, message_id = found
                store.save_feedback(paper_id, label)
                counts["saved"] += 1
                try:
                    client.edit_markup(message_id, keyboard(paper_id, selected=label))
                except Exception as exc:
                    # 按鈕只是顯示用，回饋已經存好了
                    logger.warning("回饋已記錄，但更新按鈕失敗：%s", exc)
            offset = updates[-1]["update_id"] + 1

    logger.info("收集完成：記錄 %d 筆回饋，略過 %d 筆更新", counts["saved"], counts["ignored"])
    return counts


def _retry_note(config: Config) -> str:
    """通知裡說明接下來會怎麼處理。"""
    try:
        window = config.retry.validated()
    except ValueError:
        window = None
    if window is None:
        return "不會自動重試，請稍後手動重跑 daily 與 push。"
    return f"每天 {window[0]:02d}:00～{window[1]:02d}:00 每小時自動重試，成功後會補推。"


def notify_fetch_failure(config: Config, error: Exception) -> None:
    """抓取失敗時用 Telegram 通知。同一段連續失敗只通知第一次。

    通知只是附加功能：Telegram 沒設定或發送失敗都只記錄，不影響抓取結果與退出碼。
    """
    try:
        token, chat_id = config.telegram.credentials()
    except ValueError:
        logger.info("未設定 Telegram，不發送抓取失敗通知")
        return
    try:
        with Store(config.db) as store:
            runs = store.recent_runs(limit=2)
        if len(runs) > 1 and runs[1]["status"] == "failed":
            logger.info("前一次抓取也失敗，已通知過，不重複通知")
            return
        reason = str(error)
        if reason.startswith(LIMIT_ERROR_PREFIX):
            next_step = "需要調高 config.ini 的 max_results 後重跑 daily，系統不會自動重試。"
        else:
            next_step = _retry_note(config)
        TelegramClient(token, chat_id).send(
            "⚠️ <b>arXiv 論文抓取失敗，今天先不推送</b>\n\n"
            f"原因：{html.escape(reason[:300])}\n\n"
            f"{html.escape(next_step)}"
        )
        logger.info("已發送抓取失敗通知")
    except Exception as exc:
        logger.warning("抓取失敗通知發送失敗：%s", exc)


def _needs_retry(run: dict, now: datetime) -> bool:
    """最近一次抓取是否該由補抓重來。上限錯誤要操作者調設定，重抓也沒用。"""
    if run["status"] == "failed":
        return not (run["error"] or "").startswith(LIMIT_ERROR_PREFIX)
    if run["status"] == "running":
        # 剛開始的可能還在跑，重抓會跟它搶
        return run["started_at"] is not None and now - run["started_at"] >= RUNNING_STALE
    return False


def run_catch_up(config: Config) -> bool:
    """collect 之後檢查：最近一次抓取沒成功，就在 [RETRY] 時段內重抓，成功才推送。

    自己處理所有例外，才不會蓋掉 collect 本身的錯誤。

    Returns:
        沒事可做或補抓補推成功為 True；設定錯誤、重抓或推送失敗為 False。
    """
    try:
        window = config.retry.validated()
        if window is None or not window[0] <= localnow().hour < window[1]:
            return True
        with Store(config.db) as store:
            store.init_schema()
            runs = store.recent_runs(limit=1)
            now = store.db_now()
        if not runs or not _needs_retry(runs[0], now):
            return True

        logger.info("最近一次抓取狀態為 %s，重新抓取", runs[0]["status"])
        try:
            run_fetch(config)
        except Exception as exc:
            notify_fetch_failure(config, exc)
            logger.error("補抓仍失敗，下一次 collect 在補抓時段內會再試")
            return False
        run_push(config)
        return True
    except Exception as exc:
        logger.error("補抓失敗：%s", exc)
        return False


def cmd_init_db(args: argparse.Namespace, config: Config) -> int:
    with Store(config.db) as store:
        store.init_schema()
    print(f"資料庫 {config.db.database} 與資料表已就緒")
    return 0


def cmd_daily(args: argparse.Namespace, config: Config) -> int:
    try:
        run_fetch(config)
    except Exception as exc:
        notify_fetch_failure(config, exc)
        raise
    return 0


def cmd_backfill(args: argparse.Namespace, config: Config) -> int:
    since = utcnow() - timedelta(days=args.days)
    run_fetch(config, since=since)
    return 0


def cmd_push(args: argparse.Namespace, config: Config) -> int:
    run_push(config, dry_run=args.dry_run)
    return 0


def cmd_collect(args: argparse.Namespace, config: Config) -> int:
    # 憑證錯誤要在連線資料庫前擋下；補抓推送也需要憑證，一起不做
    config.telegram.credentials()
    # 回饋收集失敗也要補抓；補抓的錯誤自己記錄，收集的例外照樣往外拋
    try:
        run_collect(config)
    finally:
        caught_up = run_catch_up(config)
    return 0 if caught_up else 1


def cmd_status(args: argparse.Namespace, config: Config) -> int:
    with Store(config.db) as store:
        store.init_schema()
        total = store.count_papers()
        runs = store.recent_runs(limit=args.limit)
        summary = store.feedback_summary()

    labels = summary["labels"]
    answered = sum(labels.values())
    rate = answered / summary["pushed"] if summary["pushed"] else 0
    print(f"訂閱分類：{', '.join(config.arxiv.categories)}")
    print(f"資料庫現有論文：{total} 篇")
    print(
        f"推送 {summary['pushed']} 篇，回饋 {answered} 篇（回饋率 {rate:.0%}）："
        f"👎 {labels.get(0, 0)}  👍 {labels.get(1, 0)}  ⭐ {labels.get(2, 0)}\n"
    )

    if not runs:
        print("尚無執行紀錄。先跑一次 daily 吧。")
        return 0

    print(f"{'id':>4}  {'狀態':<8} {'區間終點':<20} {'取回':>5} {'新增':>5}")
    print("-" * 52)
    for run in runs:
        print(
            f"{run['id']:>4}  {run['status']:<8} "
            f"{str(run['window_end']):<20} "
            f"{run['fetched']:>5} {run['new_count']:>5}"
        )
        if run["error"]:
            print(f"      錯誤：{run['error']}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m arxiv_digest",
        description="arXiv 每日論文摘要",
    )
    parser.add_argument("--config", help="設定檔路徑（預設為專案根目錄的 config.ini）")
    parser.add_argument("-v", "--verbose", action="store_true", help="顯示除錯訊息")

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="建立資料庫與資料表")
    sub.add_parser("daily", help="抓取上次執行至今的新論文")

    backfill = sub.add_parser("backfill", help="回頭補抓過去幾天")
    backfill.add_argument("--days", type=int, default=7, help="回溯天數（預設 7）")

    status = sub.add_parser("status", help="看最近的執行紀錄")
    status.add_argument("--limit", type=int, default=10, help="顯示幾筆（預設 10）")

    push = sub.add_parser("push", help="推送今天的論文到 Telegram")
    push.add_argument("--dry-run", action="store_true", help="只印出內容，不發送也不記錄")

    sub.add_parser("collect", help="收集 Telegram 按鈕回饋，抓取失敗時補抓補推")

    return parser


COMMANDS = {
    "init-db": cmd_init_db,
    "daily": cmd_daily,
    "backfill": cmd_backfill,
    "status": cmd_status,
    "push": cmd_push,
    "collect": cmd_collect,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    # 輸出導向檔案或管線時，Windows 預設編碼印不出 emoji；替換掉而不是整個指令失敗
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    try:
        config = load_config(args.config)
    except (FileNotFoundError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 1

    try:
        return COMMANDS[args.command](args, config)
    except Exception as exc:
        logger.error("執行失敗：%s", exc)
        return 1
