"""Telegram 推送與回饋：訊息格式、回饋按鈕、Bot API 呼叫。

按鈕的 callback data 固定為 fb:<paper_id>:<label>，label 0=沒興趣、
1=有興趣、2=超想讀。收集回饋時靠這個格式對回論文，改動前要一併調整收集端。
"""

from __future__ import annotations

import html
from dataclasses import dataclass, field

import requests

from arxiv_digest.translator import Translation

API_BASE = "https://api.telegram.org"

# 同一個聊天室每秒最多約 1 則，超過會被限流
SEND_INTERVAL = 1.0

# 摘要節錄長度；完整摘要常超過 1000 字，手機上太長
SUMMARY_LIMIT = 300
# 中文摘要通常 300～600 字；上限讓訊息保持在 Telegram 的 4096 字元內
TRANSLATED_SUMMARY_LIMIT = 1500
AUTHOR_LIMIT = 3

BUTTONS = (("👎 沒興趣", 0), ("👍 有興趣", 1), ("⭐ 超想讀", 2))

# getUpdates 單次最多取幾筆（Telegram 上限 100）
UPDATE_LIMIT = 100


class TelegramError(RuntimeError):
    """Telegram 發送失敗。訊息已遮蔽 bot token。"""


@dataclass
class PushPaper:
    """推送需要的論文欄位。"""

    id: int
    arxiv_id: str
    title: str
    summary: str
    categories: str
    authors: list[str] = field(default_factory=list)


def _clean(text: str | None) -> str:
    """合併 Atom 內容裡的換行與多餘空白。"""
    return " ".join((text or "").split())


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def format_message(paper: PushPaper, translation: Translation | None = None) -> str:
    """組出 HTML 格式的訊息內容。先截斷再跳脫，避免把 &amp; 之類切成兩半。

    有翻譯時：中文標題、英文原標題、作者、分類、完整中文摘要；沒有時維持英文格式。
    """
    authors = ", ".join(paper.authors[:AUTHOR_LIMIT])
    if len(paper.authors) > AUTHOR_LIMIT:
        authors += f" 等 {len(paper.authors)} 人"

    categories = ", ".join(c.strip() for c in (paper.categories or "").split(",") if c.strip())
    link = f"https://arxiv.org/abs/{paper.arxiv_id}"
    footer = f'<a href="{link}">arXiv:{html.escape(paper.arxiv_id)}</a>'

    if translation is not None:
        summary = _clip(_clean(translation.summary_zh), TRANSLATED_SUMMARY_LIMIT)
        return (
            f"<b>{html.escape(_clean(translation.title_zh))}</b>\n"
            f"{html.escape(_clean(paper.title))}\n"
            f"{html.escape(authors)}\n"
            f"<i>{html.escape(categories)}</i>\n\n"
            f"{html.escape(summary)}\n\n"
            f"{footer}"
        )

    summary = _clip(_clean(paper.summary), SUMMARY_LIMIT)
    return (
        f"<b>{html.escape(_clean(paper.title))}</b>\n"
        f"{html.escape(authors)}\n"
        f"<i>{html.escape(categories)}</i>\n\n"
        f"{html.escape(summary)}\n\n"
        f"{footer}"
    )


def keyboard(paper_id: int, selected: int | None = None) -> dict:
    """一列三個回饋按鈕。selected 為已記錄的標籤，在該按鈕前加 ✅，其他仍可改按。"""
    return {
        "inline_keyboard": [[
            {
                "text": ("✅ " if label == selected else "") + text,
                "callback_data": f"fb:{paper_id}:{label}",
            }
            for text, label in BUTTONS
        ]]
    }


class TelegramClient:
    """呼叫 Bot API。所有錯誤都轉成已遮蔽 token 的 TelegramError。"""

    def __init__(self, token: str, chat_id: str, session: requests.Session | None = None):
        self.token = token
        self.chat_id = chat_id
        self.session = session or requests.Session()

    def _mask(self, text: str) -> str:
        return text.replace(self.token, "<bot_token>") if self.token else text

    def send(self, text: str, reply_markup: dict) -> int:
        """送出一則訊息，回傳 Telegram 的 message_id。"""
        result = self._call("sendMessage", {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "link_preview_options": {"is_disabled": True},
            "reply_markup": reply_markup,
        })
        return result["message_id"]

    def get_updates(self, offset: int | None) -> list[dict]:
        """取得待處理更新。帶 offset 呼叫時，update_id 小於 offset 的更新即被確認。"""
        payload = {"timeout": 0, "limit": UPDATE_LIMIT, "allowed_updates": ["callback_query"]}
        if offset is not None:
            payload["offset"] = offset
        return self._call("getUpdates", payload)

    def edit_markup(self, message_id: int, reply_markup: dict) -> None:
        """更新訊息按鈕。內容完全相同時 Telegram 回 400 not modified，視為成功。"""
        try:
            self._call("editMessageReplyMarkup", {
                "chat_id": self.chat_id,
                "message_id": message_id,
                "reply_markup": reply_markup,
            })
        except TelegramError as exc:
            if "message is not modified" not in str(exc):
                raise

    def _call(self, method: str, payload: dict):
        """呼叫一個 Bot API 方法，回傳 result 欄位。"""
        url = f"{API_BASE}/bot{self.token}/{method}"
        try:
            response = self.session.post(url, json=payload, timeout=30)
            try:
                body = response.json()
            except ValueError:
                body = {}
        except Exception as exc:
            # from None：例外鏈裡的網址含 token，不能跟著 traceback 印出來
            raise TelegramError(self._mask(f"Telegram 連線失敗：{exc}")) from None

        if response.status_code == 200 and body.get("ok"):
            return body["result"]

        description = self._mask(str(body.get("description", "")))
        if response.status_code == 403:
            raise TelegramError(
                f"Telegram 拒絕發送（403）：請先在 Telegram 對你的 bot 按 Start，"
                f"並確認 chat_id 正確。{description}"
            )
        raise TelegramError(f"Telegram 回應 {response.status_code}：{description}")
