"""MySQL 存取：建表、去重寫入、執行紀錄。

與期中專案的差異：

1. 唯一鍵改用 arxiv_id（不含版本號），論文改版不會重複入庫。
2. 多了 runs 表記錄每次執行涵蓋的時間區間，斷點續傳靠它。
3. 多了 scores / feedback 兩張表，分別存 LLM 評分與使用者回饋。
   feedback 累積起來就是未來做個人化模型的訓練資料。
4. 每篇論文獨立 commit：論文寫進去但作者寫失敗時會整篇回滾，
   不會留下沒有作者的孤兒論文。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import pymysql
from pymysql.connections import Connection

from arxiv_digest.config import DBConfig
from arxiv_digest.fetcher import Paper

logger = logging.getLogger(__name__)

SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS papers(
        id         INT AUTO_INCREMENT PRIMARY KEY,
        arxiv_id   VARCHAR(64) UNIQUE NOT NULL,   -- 不含版本號，用來擋重複
        title      VARCHAR(500) NOT NULL,
        summary    TEXT,
        published  DATE,
        updated    DATE,
        categories VARCHAR(255),
        link       VARCHAR(500),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_published (published)
    ) CHARACTER SET utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS authors(
        id       INT AUTO_INCREMENT PRIMARY KEY,
        paper_id INT NOT NULL,
        name     VARCHAR(255) NOT NULL,
        FOREIGN KEY (paper_id) REFERENCES papers(id) ON DELETE CASCADE,
        INDEX idx_paper (paper_id)
    ) CHARACTER SET utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS scores(
        id        INT AUTO_INCREMENT PRIMARY KEY,
        paper_id  INT NOT NULL,
        score     TINYINT NOT NULL,              -- 0-10
        reason    VARCHAR(500),
        model     VARCHAR(50),
        scored_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (paper_id) REFERENCES papers(id) ON DELETE CASCADE,
        INDEX idx_score (score)
    ) CHARACTER SET utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS feedback(
        id         INT AUTO_INCREMENT PRIMARY KEY,
        paper_id   INT NOT NULL,
        label      TINYINT NOT NULL,             -- 1=有興趣 0=沒興趣
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (paper_id) REFERENCES papers(id) ON DELETE CASCADE,
        UNIQUE KEY uniq_paper (paper_id)         -- 同一篇只留一次表態
    ) CHARACTER SET utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS runs(
        id           INT AUTO_INCREMENT PRIMARY KEY,
        window_start DATETIME NOT NULL,          -- 本次涵蓋的查詢區間
        window_end   DATETIME NOT NULL,
        started_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        finished_at  TIMESTAMP NULL,
        status       VARCHAR(20) NOT NULL,       -- running / success / failed
        fetched      INT DEFAULT 0,              -- API 取回幾筆
        new_count    INT DEFAULT 0,              -- 實際新增幾筆
        error        VARCHAR(500),
        INDEX idx_status (status, window_end)
    ) CHARACTER SET utf8mb4
    """,
]


class Store:
    """資料庫存取。可用 with 語法管理連線。"""

    def __init__(self, config: DBConfig):
        self.config = config
        self.db: Connection | None = None

    # ---------------- 連線管理 ----------------

    def connect(self) -> None:
        """連線並確保資料庫存在。"""
        # 先不指定 database 連進去，才能建立它
        self.db = pymysql.connect(
            host=self.config.host,
            user=self.config.user,
            password=self.config.password,
            port=self.config.port,
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
        )
        with self.db.cursor() as cursor:
            cursor.execute(
                f"CREATE DATABASE IF NOT EXISTS `{self.config.database}` "
                f"CHARACTER SET utf8mb4"
            )
            cursor.execute(f"USE `{self.config.database}`")
        self.db.commit()

    def close(self) -> None:
        if self.db:
            self.db.close()
            self.db = None

    def __enter__(self) -> "Store":
        self.connect()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _require_db(self) -> Connection:
        if self.db is None:
            raise RuntimeError("尚未連線，請先呼叫 connect() 或使用 with 語法")
        return self.db

    # ---------------- 建表 ----------------

    def init_schema(self) -> None:
        """建立所有資料表。已存在時不做事。"""
        db = self._require_db()
        with db.cursor() as cursor:
            for statement in SCHEMA_STATEMENTS:
                cursor.execute(statement)
        db.commit()
        # 每個指令都會呼叫這個方法，用 info 會讓 daily / status 的輸出多一行雜訊
        logger.debug("資料表建立完成：papers / authors / scores / feedback / runs")

    # ---------------- 論文寫入 ----------------

    def save_papers(self, papers: list[Paper]) -> tuple[int, int]:
        """寫入論文與作者，重複的略過。

        Returns:
            (新增筆數, 略過的重複筆數)
        """
        db = self._require_db()
        new_count = 0
        dup_count = 0

        for paper in papers:
            try:
                with db.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO papers
                            (arxiv_id, title, summary, published, updated,
                             categories, link)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            paper.arxiv_id,
                            paper.title,
                            paper.summary,
                            paper.published,
                            paper.updated,
                            paper.categories,
                            paper.link,
                        ),
                    )
                    paper_id = cursor.lastrowid

                    for author in paper.authors:
                        cursor.execute(
                            "INSERT INTO authors (paper_id, name) VALUES (%s, %s)",
                            (paper_id, author),
                        )

                # 一篇論文連同作者一起 commit，中途失敗就整篇回滾
                db.commit()
                new_count += 1

            except pymysql.err.IntegrityError:
                # arxiv_id 撞到 UNIQUE，代表這篇抓過了
                db.rollback()
                dup_count += 1

            except pymysql.err.MySQLError:
                db.rollback()
                logger.exception("寫入論文失敗，略過：%s", paper.arxiv_id)

        return new_count, dup_count

    # ---------------- 執行紀錄（斷點續傳） ----------------

    def last_success_window_end(self) -> datetime | None:
        """上次成功執行涵蓋到的時間點；從未成功執行過則回傳 None。"""
        db = self._require_db()
        with db.cursor() as cursor:
            cursor.execute(
                """
                SELECT window_end
                FROM runs
                WHERE status = 'success'
                ORDER BY window_end DESC
                LIMIT 1
                """
            )
            row = cursor.fetchone()
        return row["window_end"] if row else None

    def next_fetch_start(self, lookback: timedelta = timedelta(0)) -> datetime | None:
        """選最早待補起點，包含首次失敗與尚未完成的舊區間。

        成功終點往前 lookback 重查，補上當時尚未公告的論文。失敗區間起點
        已含當次回看，直接沿用；再減一次會讓連續失敗的起點不斷往前漂移。
        只有較晚執行且完整涵蓋舊區間的成功紀錄，才解除該次重試需求。
        不刪改失敗紀錄，保留排錯資訊。此策略假設單一抓取工作執行。
        """
        latest = self.last_success_window_end()
        if latest is not None:
            latest -= lookback
        with self._require_db().cursor() as cursor:
            cursor.execute(
                """
                SELECT MIN(r.window_start) AS window_start
                FROM runs AS r
                WHERE r.status IN ('failed', 'running')
                  AND NOT EXISTS (
                      SELECT 1 FROM runs AS s
                      WHERE s.status = 'success'
                        AND s.id > r.id
                        AND s.window_start <= r.window_start
                        AND s.window_end >= r.window_end
                  )
                """
            )
            pending = cursor.fetchone()["window_start"]
        candidates = [value for value in (latest, pending) if value is not None]
        return min(candidates) if candidates else None

    def start_run(self, window_start: datetime, window_end: datetime) -> int:
        """記錄一次執行的開始，回傳 run_id。"""
        db = self._require_db()
        with db.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO runs (window_start, window_end, status)
                VALUES (%s, %s, 'running')
                """,
                (window_start, window_end),
            )
            run_id = cursor.lastrowid
        db.commit()
        return run_id

    def finish_run(
        self,
        run_id: int,
        status: str,
        fetched: int = 0,
        new_count: int = 0,
        error: str | None = None,
    ) -> None:
        """標記一次執行的結果。只有 success 的紀錄會被斷點續傳採用。"""
        db = self._require_db()
        with db.cursor() as cursor:
            cursor.execute(
                """
                UPDATE runs
                SET status = %s, fetched = %s, new_count = %s,
                    error = %s, finished_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (status, fetched, new_count, error[:500] if error else None, run_id),
            )
        db.commit()

    def recent_runs(self, limit: int = 10) -> list[dict]:
        """最近幾次的執行紀錄。"""
        db = self._require_db()
        with db.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, window_start, window_end, started_at, finished_at,
                       status, fetched, new_count, error
                FROM runs
                ORDER BY id DESC
                LIMIT %s
                """,
                (limit,),
            )
            return list(cursor.fetchall())

    def count_papers(self) -> int:
        """目前資料庫裡有幾篇論文。"""
        db = self._require_db()
        with db.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) AS n FROM papers")
            return cursor.fetchone()["n"]
