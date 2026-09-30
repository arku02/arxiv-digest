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

# 回饋備份的預設資料夾名稱，放在專案根目錄旁邊，不在這個 repo 裡
DEFAULT_BACKUP_DIRNAME = "arxiv-digest-data"

# config.ini.example 的範例值開頭，例如 YOUR_BOT_TOKEN_HERE
PLACEHOLDER_PREFIX = "YOUR_"


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
    # daily 每次往回重查幾天。arXiv 論文公告後 API 才查得到，
    # 週五截止後的投稿要到週一晚上（ET）才公告，最長約 3 天多
    lookback_days: int = 4

    def __post_init__(self) -> None:
        # bool 是 int 的子類別，要排除；在連線與請求前就擋下錯誤設定
        if type(self.lookback_days) is not int or self.lookback_days < 0:
            raise ValueError("config.ini 的 [ARXIV] lookback_days 必須是非負整數")


@dataclass(frozen=True)
class TelegramConfig:
    """推送設定。保存原始字串，push 時才驗證，缺少或填錯不影響 daily。"""

    bot_token: str = ""
    chat_id: str = ""
    daily_limit: str = "10"

    def limit(self) -> int:
        """每天推送篇數，必須是正整數。"""
        try:
            value = int(self.daily_limit)
        except ValueError:
            value = 0
        if value <= 0:
            raise ValueError("config.ini 的 [TELEGRAM] daily_limit 必須是正整數")
        return value

    def credentials(self) -> tuple[str, str]:
        """回傳 (bot_token, chat_id)；還沒填或仍是範例值時提示去 config.ini 填。"""
        values = (self.bot_token.strip(), self.chat_id.strip())
        if any(not v or v.startswith(PLACEHOLDER_PREFIX) for v in values):
            raise ValueError(
                "尚未設定 Telegram：請在 config.ini 的 [TELEGRAM] 填入 bot_token 與 chat_id"
                "（取得方式見 config.ini.example）。只想預覽可用 push --dry-run"
            )
        return values


@dataclass(frozen=True)
class TranslateConfig:
    """推送翻譯設定。保存原始字串，push 時才驗證，填錯不影響 daily。"""

    enabled: str = "false"
    model: str = "qwen3.5:9b"
    url: str = "http://127.0.0.1:11434"
    timeout: str = "300"

    def validated(self) -> tuple[str, str, float] | None:
        """關閉時回傳 None；開啟時回傳 (model, url, timeout 秒)。"""
        flag = ConfigParser.BOOLEAN_STATES.get(self.enabled.strip().lower())
        if flag is None:
            raise ValueError("config.ini 的 [TRANSLATE] enabled 必須是 true 或 false")
        if not flag:
            return None
        try:
            timeout = float(self.timeout)
        except ValueError:
            timeout = 0
        if not timeout > 0:
            raise ValueError("config.ini 的 [TRANSLATE] timeout 必須是正數（秒）")
        return self.model.strip(), self.url.strip().rstrip("/"), timeout


@dataclass(frozen=True)
class RetryConfig:
    """抓取失敗後的每小時補抓設定。保存原始字串，補抓時才驗證，填錯不影響 daily。"""

    enabled: str = "true"
    # 本機時間，start_hour <= 現在小時 < end_hour 才補抓；避開 09:30 的 daily 與半夜推送
    start_hour: str = "10"
    end_hour: str = "22"

    def validated(self) -> tuple[int, int] | None:
        """關閉時回傳 None；開啟時回傳 (start_hour, end_hour)。"""
        flag = ConfigParser.BOOLEAN_STATES.get(self.enabled.strip().lower())
        if flag is None:
            raise ValueError("config.ini 的 [RETRY] enabled 必須是 true 或 false")
        if not flag:
            return None
        hours = []
        for name, text in (("start_hour", self.start_hour), ("end_hour", self.end_hour)):
            value = text.strip()
            if not value.isdigit() or int(value) > 24:
                raise ValueError(f"config.ini 的 [RETRY] {name} 必須是 0～24 的整數")
            hours.append(int(value))
        if hours[0] >= hours[1]:
            raise ValueError("config.ini 的 [RETRY] start_hour 必須小於 end_hour")
        return hours[0], hours[1]


@dataclass(frozen=True)
class BackupConfig:
    """回饋備份設定。保存原始字串，backup 時才驗證，填錯不影響其他指令。"""

    # 空字串代表預設：專案根目錄旁的 arxiv-digest-data（私人 repo 的 clone）
    dir: str = ""
    push: str = "true"

    def resolved(self) -> tuple[Path, bool]:
        """回傳 (備份資料夾, 是否 git push)。相對路徑以專案根目錄為基準。"""
        flag = ConfigParser.BOOLEAN_STATES.get(self.push.strip().lower())
        if flag is None:
            raise ValueError("config.ini 的 [BACKUP] push 必須是 true 或 false")
        root = DEFAULT_CONFIG_PATH.parent
        text = self.dir.strip()
        directory = root / text if text else root.parent / DEFAULT_BACKUP_DIRNAME
        return directory, flag


@dataclass(frozen=True)
class Config:
    db: DBConfig
    arxiv: ArxivConfig
    telegram: TelegramConfig = TelegramConfig()
    translate: TranslateConfig = TranslateConfig()
    retry: RetryConfig = RetryConfig()
    backup: BackupConfig = BackupConfig()


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
        lookback_days=parser.getint("ARXIV", "lookback_days", fallback=4),
    )

    telegram = TelegramConfig(
        bot_token=parser.get("TELEGRAM", "bot_token", fallback=""),
        chat_id=parser.get("TELEGRAM", "chat_id", fallback=""),
        daily_limit=parser.get("TELEGRAM", "daily_limit", fallback="10"),
    )

    translate = TranslateConfig(
        enabled=parser.get("TRANSLATE", "enabled", fallback="false"),
        model=parser.get("TRANSLATE", "model", fallback="qwen3.5:9b"),
        url=parser.get("TRANSLATE", "url", fallback="http://127.0.0.1:11434"),
        timeout=parser.get("TRANSLATE", "timeout", fallback="300"),
    )

    retry = RetryConfig(
        enabled=parser.get("RETRY", "enabled", fallback="true"),
        start_hour=parser.get("RETRY", "start_hour", fallback="10"),
        end_hour=parser.get("RETRY", "end_hour", fallback="22"),
    )

    backup = BackupConfig(
        dir=parser.get("BACKUP", "dir", fallback=""),
        push=parser.get("BACKUP", "push", fallback="true"),
    )

    return Config(
        db=db, arxiv=arxiv, telegram=telegram, translate=translate, retry=retry, backup=backup
    )
