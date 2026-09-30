"""arXiv API 抓取：增量查詢、分頁、限速、重試。

改造自期中專案的 Arxiv 類別，主要差異有四點：

1. 用 submittedDate 區間做增量抓取，而不是每次抓「最新 N 篇」。
   這樣筆電關機幾天後開機也能把中間漏掉的補齊。
2. 解析出不含版本號的 arxiv_id，避免論文從 v1 改版到 v2 時被當成新論文重複入庫。
3. 加上限速與重試 —— arXiv 官方要求請求之間至少間隔 3 秒。
4. 自動分頁，單次執行的總量由 max_results 設上限，避免久未執行時一口氣拉爆。
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime

import requests
from bs4 import BeautifulSoup

from arxiv_digest.config import ArxivConfig

logger = logging.getLogger(__name__)

API_URL = "http://export.arxiv.org/api/query"

# arXiv 的 id 網址形如 http://arxiv.org/abs/2401.12345v2
# 新式 id 為 2401.12345，舊式為 cs/0501001，兩者都可能帶 vN 版本後綴
_ID_PATTERN = re.compile(r"/abs/(?P<id>.+?)(?:v\d+)?$")

# submittedDate 區間要求的時間格式（UTC）
_DATE_FORMAT = "%Y%m%d%H%M"

# 上限錯誤訊息的開頭。補抓靠它從 runs.error 認出「要操作者調設定、重試也沒用」的失敗
LIMIT_ERROR_PREFIX = "已達單次上限"

# 被限流（429）或服務暫停（503）時，request_delay 的指數退避只有幾秒，太短。
# 有 Retry-After 就照它等，但不超過上限；沒有就等 60、120 秒
RATE_LIMIT_STATUS = (429, 503)
RATE_LIMIT_BACKOFF = 60.0
MAX_RETRY_AFTER = 300


class FetchLimitExceeded(RuntimeError):
    """The requested window still contains papers beyond the configured cap."""


@dataclass
class Paper:
    """一篇論文。欄位對應資料庫的 papers 表。"""

    arxiv_id: str
    title: str
    summary: str
    published: str          # YYYY-MM-DD
    updated: str            # YYYY-MM-DD
    categories: str         # 逗號分隔，例如 "cs.CV,cs.LG"
    link: str
    authors: list[str] = field(default_factory=list)


def extract_arxiv_id(id_url: str) -> str:
    """從 arXiv 的 id 網址取出不含版本號的識別碼。

    >>> extract_arxiv_id("http://arxiv.org/abs/2401.12345v2")
    '2401.12345'
    >>> extract_arxiv_id("http://arxiv.org/abs/cs/0501001v1")
    'cs/0501001'
    """
    match = _ID_PATTERN.search(id_url.strip())
    if not match:
        # 格式不符時退回原字串，讓資料還是進得去，之後從資料看得出異常
        logger.warning("無法解析 arxiv_id：%s", id_url)
        return id_url.strip()
    return match.group("id")


def _retry_after(response) -> int | None:
    """讀 Retry-After 的秒數，上限 MAX_RETRY_AFTER；沒有或是日期格式就回傳 None。"""
    value = str(response.headers.get("Retry-After", "")).strip()
    if not value.isdigit():
        return None
    return min(int(value), MAX_RETRY_AFTER)


class ArxivFetcher:
    """對 arXiv API 發送增量查詢。"""

    def __init__(self, config: ArxivConfig, session: requests.Session | None = None):
        self.config = config
        self.session = session or requests.Session()
        self._last_request_at: float = 0.0

    # ---------------- 對外介面 ----------------

    def fetch(self, since: datetime, until: datetime) -> list[Paper]:
        """抓取 [since, until) 區間內提交的論文。

        Args:
            since: 區間起點（UTC）。
            until: 區間終點（UTC）。

        Returns:
            論文列表，依提交時間由舊到新。

        Raises:
            FetchLimitExceeded: 已達上限且探查仍有資料；呼叫端不得推進成功起點。
        """
        for name in ("page_size", "max_results"):
            value = getattr(self.config, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} 必須是正整數")
        if since >= until:
            logger.info("查詢區間為空（since=%s >= until=%s），跳過", since, until)
            return []

        query = self._build_query(since, until)
        logger.info("查詢字串：%s", query)

        papers: list[Paper] = []
        start = 0

        while len(papers) < self.config.max_results:
            # 這一頁要抓幾筆：不超過 page_size，也不超過剩餘額度
            remaining = self.config.max_results - len(papers)
            page_size = min(self.config.page_size, remaining)

            xml_text = self._request(query, start=start, page_size=page_size)
            page = self._parse(xml_text)

            if not page:
                break

            papers.extend(page)
            logger.info("已取得 %d 筆（本頁 %d 筆）", len(papers), len(page))

            # 回傳筆數少於請求筆數，代表已經是最後一頁
            if len(page) < page_size:
                break

            start += len(page)

        if len(papers) >= self.config.max_results:
            # One extra record distinguishes an exact fit from truncation. Keep the
            # same query, ordering, throttle and retry policy; never save the probe.
            probe = self._parse(self._request(query, start=len(papers), page_size=1))
            if probe:
                raise FetchLimitExceeded(
                    f"{LIMIT_ERROR_PREFIX} {self.config.max_results} 筆，區間尚未抓完；"
                    f"查詢區間 UTC {since:%Y-%m-%d %H:%M} ~ {until:%Y-%m-%d %H:%M}。"
                    "本批次未寫入，續抓起點保留。請調高 max_results 後重跑；"
                    "系統不會自動調高上限。"
                )

        return papers

    # ---------------- 內部實作 ----------------

    def _build_query(self, since: datetime, until: datetime) -> str:
        """組出查詢字串：訂閱分類的聯集，交集提交時間區間。"""
        cats = " OR ".join(f"cat:{c}" for c in self.config.categories)
        window = (
            f"submittedDate:[{since.strftime(_DATE_FORMAT)}"
            f" TO {until.strftime(_DATE_FORMAT)}]"
        )
        return f"({cats}) AND {window}"

    def _throttle(self) -> None:
        """確保兩次請求之間至少間隔 request_delay 秒。"""
        elapsed = time.monotonic() - self._last_request_at
        wait = self.config.request_delay - elapsed
        if wait > 0:
            time.sleep(wait)
        self._last_request_at = time.monotonic()

    def _request(
        self,
        query: str,
        start: int,
        page_size: int,
        max_retries: int = 3,
    ) -> str:
        """發送一次 API 請求，失敗時以指數退避重試；被限流時等久一點。"""
        params = {
            "search_query": query,
            "start": start,
            "max_results": page_size,
            "sortBy": "submittedDate",
            "sortOrder": "ascending",   # 由舊到新，分頁時順序才穩定
        }

        last_error: Exception | None = None

        for attempt in range(max_retries):
            self._throttle()
            backoff = self.config.request_delay * (2 ** attempt)
            try:
                response = self.session.get(API_URL, params=params, timeout=30)
                if response.status_code == 200:
                    return response.text
                last_error = RuntimeError(f"HTTP {response.status_code}")
                if response.status_code in RATE_LIMIT_STATUS:
                    wait = _retry_after(response)
                    backoff = RATE_LIMIT_BACKOFF * (2 ** attempt) if wait is None else wait
            except requests.RequestException as exc:
                last_error = exc

            if attempt + 1 == max_retries:
                break
            logger.warning(
                "請求失敗（%s），%.1f 秒後重試（第 %d/%d 次）",
                last_error, backoff, attempt + 2, max_retries,
            )
            time.sleep(backoff)

        raise RuntimeError(f"arXiv API 連續 {max_retries} 次請求失敗：{last_error}")

    def _parse(self, xml_text: str) -> list[Paper]:
        """把 Atom XML 解析成 Paper 列表。"""
        soup = BeautifulSoup(xml_text, "xml")

        papers: list[Paper] = []
        for entry in soup.find_all("entry"):
            id_url = entry.find("id").text
            categories = [
                c.get("term") for c in entry.find_all("category") if c.get("term")
            ]

            papers.append(
                Paper(
                    arxiv_id=extract_arxiv_id(id_url),
                    title=entry.find("title").text.strip(),
                    summary=entry.find("summary").text.strip(),
                    published=entry.find("published").text[:10],
                    updated=entry.find("updated").text[:10],
                    categories=",".join(categories),
                    link=id_url.strip(),
                    authors=[a.find("name").text.strip() for a in entry.find_all("author")],
                )
            )

        return papers
