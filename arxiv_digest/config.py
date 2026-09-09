"""設定讀取。

沿用期中專案 config.ini 的做法：帳密與 API key 都放在不進版控的
設定檔裡，程式碼本身不含任何機密。
"""

from __future__ import annotations

from configparser import ConfigParser
from dataclasses import dataclass
from pathlib import Path

# 專案根目錄下的 config.ini（arxiv_digest/ 的上一層）
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.ini"


@dataclass(frozen=True)
class DBConfig:
    """MySQL 連線設定。"""

    host: str
    user: str
    password: str
    port: int
    database: str


@dataclass(frozen=True)
class ArxivConfig:
    """抓取行為設定。"""

    categories: list[str]
    page_size: int
    max_results: int
    request_delay: float
    initial_backfill_days: int


@dataclass(frozen=True)
class Config:
    db: DBConfig
    arxiv: ArxivConfig


def load_config(path: Path | str | None = None) -> Config:
    """讀取 config.ini，回傳結構化的設定物件。

    Raises:
        FileNotFoundError: 設定檔不存在時，訊息會指向 config.ini.example。
    """
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH

    if not config_path.exists():
        raise FileNotFoundError(
            f"找不到設定檔 {config_path}\n"
            f"請複製 config.ini.example 為 config.ini 後填入你的設定："
            f"\n    cp config.ini.example config.ini"
        )

    parser = ConfigParser()
    parser.read(config_path, encoding="utf-8")

    db = DBConfig(
        host=parser.get("DB", "host"),
        user=parser.get("DB", "user"),
        password=parser.get("DB", "password"),
        port=parser.getint("DB", "port"),
        database=parser.get("DB", "database"),
    )

    # 分類字串 "cs.CV, cs.CL" -> ["cs.CV", "cs.CL"]，順手濾掉空白項
    categories = [c.strip() for c in parser.get("ARXIV", "categories").split(",")]
    categories = [c for c in categories if c]
    if not categories:
        raise ValueError("config.ini 的 [ARXIV] categories 不能是空的")

    arxiv = ArxivConfig(
        categories=categories,
        page_size=parser.getint("ARXIV", "page_size", fallback=100),
        max_results=parser.getint("ARXIV", "max_results", fallback=1000),
        request_delay=parser.getfloat("ARXIV", "request_delay", fallback=3.0),
        initial_backfill_days=parser.getint("ARXIV", "initial_backfill_days", fallback=1),
    )

    return Config(db=db, arxiv=arxiv)
