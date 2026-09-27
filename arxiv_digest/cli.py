"""命令列進入點。

    python -m arxiv_digest init-db          建立資料庫與資料表
    python -m arxiv_digest daily            抓取上次執行至今的新論文
    python -m arxiv_digest backfill --days 7  回頭補抓過去 7 天
    python -m arxiv_digest status           看最近的執行紀錄

排程只要固定跑 daily 就好。它會自己從「上次成功執行涵蓋到的時間點」接續，
所以筆電關機好幾天再開，中間的論文一樣補得回來。接續時會再往回重查
lookback_days 天，因為 arXiv 論文要公告後才查得到，上次執行時可能還看不到。
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timedelta, timezone

from arxiv_digest.config import Config, load_config
from arxiv_digest.fetcher import ArxivFetcher
from arxiv_digest.store import Store

logger = logging.getLogger("arxiv_digest")


def utcnow() -> datetime:
    """現在時間（UTC，但去掉時區資訊）。

    MySQL 的 DATETIME 不存時區，讀回來一定是 naive。全程統一用 naive UTC，
    才不會出現「aware 與 naive 相減」的 TypeError。
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


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


def cmd_init_db(args: argparse.Namespace, config: Config) -> int:
    with Store(config.db) as store:
        store.init_schema()
    print(f"資料庫 {config.db.database} 與資料表已就緒")
    return 0


def cmd_daily(args: argparse.Namespace, config: Config) -> int:
    run_fetch(config)
    return 0


def cmd_backfill(args: argparse.Namespace, config: Config) -> int:
    since = utcnow() - timedelta(days=args.days)
    run_fetch(config, since=since)
    return 0


def cmd_status(args: argparse.Namespace, config: Config) -> int:
    with Store(config.db) as store:
        store.init_schema()
        total = store.count_papers()
        runs = store.recent_runs(limit=args.limit)

    print(f"訂閱分類：{', '.join(config.arxiv.categories)}")
    print(f"資料庫現有論文：{total} 篇\n")

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

    return parser


COMMANDS = {
    "init-db": cmd_init_db,
    "daily": cmd_daily,
    "backfill": cmd_backfill,
    "status": cmd_status,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

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
