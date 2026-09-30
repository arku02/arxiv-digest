"""MySQL 存取：建表、去重寫入、執行紀錄。

與期中專案的差異：

1. 唯一鍵改用 arxiv_id（不含版本號），論文改版不會重複入庫。
2. 多了 runs 表記錄每次執行涵蓋的時間區間，斷點續傳靠它。
3. 多了 scores / feedback 兩張表，分別存 LLM 評分與使用者回饋。
   feedback 累積起來就是未來做個人化模型的訓練資料。
4. 每篇論文獨立 commit：論文寫進去但作者寫失敗時會整篇回滾，
   不會留下沒有作者的孤兒論文。
5. push_batches / pushes 記錄每次推送的候選數與每則 Telegram 訊息，
   收集回饋時靠它把按鈕點擊對回論文。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import pymysql
from pymysql.connections import Connection

from arxiv_digest.config import DBConfig
from arxiv_digest.fetcher import Paper
from arxiv_digest.notifier import PushPaper

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
        label      TINYINT NOT NULL,             -- 0=沒興趣 1=有興趣 2=超想讀
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
    """
    CREATE TABLE IF NOT EXISTS push_batches(
        id          INT AUTO_INCREMENT PRIMARY KEY,
        started_at  DATETIME NOT NULL,           -- 資料庫時間，與 papers.created_at 同一時鐘
        pool_size   INT NOT NULL,                -- 候選篇數，之後可還原抽中機率
        sent        INT DEFAULT 0,
        status      VARCHAR(20) NOT NULL,        -- running / success / failed
        error       VARCHAR(500),
        finished_at TIMESTAMP NULL,
        INDEX idx_status (status, started_at)
    ) CHARACTER SET utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS pushes(
        id         INT AUTO_INCREMENT PRIMARY KEY,
        batch_id   INT NOT NULL,
        paper_id   INT NOT NULL,
        chat_id    VARCHAR(64) NOT NULL,
        message_id BIGINT NOT NULL,              -- 收集回饋時用來對回這則訊息
        pushed_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (batch_id) REFERENCES push_batches(id),
        FOREIGN KEY (paper_id) REFERENCES papers(id) ON DELETE CASCADE,
        UNIQUE KEY uniq_paper (paper_id),        -- 同一篇只推一次
        INDEX idx_message (chat_id, message_id)
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
        logger.debug("資料表建立完成：papers / authors / scores / feedback / runs / push_batches / pushes")

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

    # ---------------- 推送紀錄 ----------------

    def db_now(self) -> datetime:
        """資料庫目前時間。papers.created_at 用的是資料庫時鐘，推送區間要跟它比。"""
        with self._require_db().cursor() as cursor:
            cursor.execute("SELECT CURRENT_TIMESTAMP AS now")
            return cursor.fetchone()["now"]

    def last_success_push_start(self) -> datetime | None:
        """最近一次成功推送批次的起點；失敗或中斷的批次不算。"""
        with self._require_db().cursor() as cursor:
            cursor.execute(
                """
                SELECT MAX(started_at) AS started_at
                FROM push_batches
                WHERE status = 'success'
                """
            )
            return cursor.fetchone()["started_at"]

    def push_pool(self, after: datetime, until: datetime) -> list[int]:
        """(after, until] 之間入庫、且從未推送過的論文 id，由小到大。"""
        with self._require_db().cursor() as cursor:
            cursor.execute(
                """
                SELECT p.id
                FROM papers AS p
                WHERE p.created_at > %s
                  AND p.created_at <= %s
                  AND NOT EXISTS (SELECT 1 FROM pushes AS s WHERE s.paper_id = p.id)
                ORDER BY p.id
                """,
                (after, until),
            )
            return [row["id"] for row in cursor.fetchall()]

    def papers_for_push(self, paper_ids: list[int]) -> list[PushPaper]:
        """讀出推送需要的欄位與作者（依作者寫入順序），回傳順序同 paper_ids。"""
        if not paper_ids:
            return []
        marks = ", ".join(["%s"] * len(paper_ids))
        with self._require_db().cursor() as cursor:
            cursor.execute(
                f"""
                SELECT id, arxiv_id, title, summary, categories
                FROM papers WHERE id IN ({marks})
                """,
                tuple(paper_ids),
            )
            papers = {row["id"]: PushPaper(**row) for row in cursor.fetchall()}
            cursor.execute(
                f"""
                SELECT paper_id, name FROM authors
                WHERE paper_id IN ({marks})
                ORDER BY id
                """,
                tuple(paper_ids),
            )
            for row in cursor.fetchall():
                papers[row["paper_id"]].authors.append(row["name"])
        return [papers[paper_id] for paper_id in paper_ids]

    def start_push_batch(self, started_at: datetime, pool_size: int) -> int:
        db = self._require_db()
        with db.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO push_batches (started_at, pool_size, status)
                VALUES (%s, %s, 'running')
                """,
                (started_at, pool_size),
            )
            batch_id = cursor.lastrowid
        db.commit()
        return batch_id

    def record_push(self, batch_id: int, paper_id: int, chat_id: str, message_id: int) -> None:
        """每送出一則就立刻 commit，中途失敗時已送出的不會重送。"""
        db = self._require_db()
        with db.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO pushes (batch_id, paper_id, chat_id, message_id)
                VALUES (%s, %s, %s, %s)
                """,
                (batch_id, paper_id, chat_id, message_id),
            )
        db.commit()

    def finish_push_batch(
        self, batch_id: int, status: str, sent: int, error: str | None = None
    ) -> None:
        db = self._require_db()
        with db.cursor() as cursor:
            cursor.execute(
                """
                UPDATE push_batches
                SET status = %s, sent = %s, error = %s, finished_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (status, sent, error[:500] if error else None, batch_id),
            )
        db.commit()

    # ---------------- 回饋 ----------------

    def pushed_paper_for_message(self, chat_id: str, message_id: int) -> int | None:
        """這則 Telegram 訊息推送的是哪篇論文；不是我們推的就回傳 None。"""
        with self._require_db().cursor() as cursor:
            cursor.execute(
                "SELECT paper_id FROM pushes WHERE chat_id = %s AND message_id = %s",
                (chat_id, message_id),
            )
            row = cursor.fetchone()
        return row["paper_id"] if row else None

    def save_feedback(self, paper_id: int, label: int) -> None:
        """寫入或覆蓋一篇論文的回饋，重複執行結果相同。

        不靠 UPDATE 的影響列數判斷是否存在：pymysql 預設不把「值沒變」的列算進去。
        """
        db = self._require_db()
        with db.cursor() as cursor:
            cursor.execute("SELECT label FROM feedback WHERE paper_id = %s", (paper_id,))
            row = cursor.fetchone()
            if row is None:
                cursor.execute(
                    "INSERT INTO feedback (paper_id, label) VALUES (%s, %s)",
                    (paper_id, label),
                )
            elif row["label"] != label:
                cursor.execute(
                    "UPDATE feedback SET label = %s WHERE paper_id = %s",
                    (label, paper_id),
                )
        db.commit()

    def feedback_summary(self) -> dict:
        """推送篇數、回饋篇數與各標籤篇數。"""
        with self._require_db().cursor() as cursor:
            cursor.execute("SELECT COUNT(*) AS n FROM pushes")
            pushed = cursor.fetchone()["n"]
            cursor.execute(
                """
                SELECT f.label, COUNT(*) AS n
                FROM feedback AS f
                WHERE EXISTS (SELECT 1 FROM pushes AS s WHERE s.paper_id = f.paper_id)
                GROUP BY f.label
                """
            )
            labels = {row["label"]: row["n"] for row in cursor.fetchall()}
        return {"pushed": pushed, "labels": labels}

    def backup_rows(self) -> list[dict]:
        """每篇已推送論文一列，附批次資訊與回饋；不含 chat_id、message_id。"""
        with self._require_db().cursor() as cursor:
            cursor.execute(
                """
                SELECT p.arxiv_id, p.title, p.categories, p.published,
                       s.batch_id, b.pool_size, b.sent AS batch_sent, s.pushed_at,
                       f.label, f.created_at AS feedback_at
                FROM pushes AS s
                JOIN papers AS p ON p.id = s.paper_id
                JOIN push_batches AS b ON b.id = s.batch_id
                LEFT JOIN feedback AS f ON f.paper_id = s.paper_id
                ORDER BY s.pushed_at, p.arxiv_id
                """
            )
            return list(cursor.fetchall())

    def count_papers(self) -> int:
        """目前資料庫裡有幾篇論文。"""
        db = self._require_db()
        with db.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) AS n FROM papers")
            return cursor.fetchone()["n"]
