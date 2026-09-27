"""本機 Ollama 翻譯：把論文標題與摘要翻成台灣用語的繁體中文。

完全在本機執行、免費，但用 CPU 跑 9B 模型每篇約 45 秒。
失敗時由呼叫端改推英文，這裡只負責「翻好」或「丟出 TranslationError」。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

import opencc
import requests

SYSTEM_PROMPT = (
    "你是專業的學術翻譯。把使用者提供的 arXiv 論文標題與摘要翻譯成台灣用語的繁體中文。"
    "要求：忠實完整翻譯，不要摘要或增刪內容；專有名詞與模型、資料集名稱第一次出現時"
    "寫成「中文（English）」，沒有通用中文譯名或沒把握的術語保留英文原文；"
    "不要使用簡體字或中國大陸用語。"
    "用語對照（左為大陸用語，右為必須使用的台灣用語）：視頻→影片、音頻→音訊、實時→即時、"
    "代碼→程式碼、信號→訊號、信息→資訊、支持→支援、魯棒性→穩健性、數據集→資料集、"
    "數據→資料、質量→品質、網絡→網路、算法→演算法、模塊→模組、優化→最佳化、默認→預設、"
    "推理（inference）→推論、蒸餾（distillation）→蒸餾。"
    "數字與比例要照原文精確翻譯，例如 four of five 是「五個中的四個」。"
)

# 要求模型以固定 JSON 格式回傳，解析失敗就視為翻譯失敗
RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "title_zh": {"type": "string"},
        "summary_zh": {"type": "string"},
    },
    "required": ["title_zh", "summary_zh"],
}

# 批次內逐篇呼叫會延續載入；推送結束約 1 分鐘後釋放 7～8 GB 記憶體
KEEP_ALIVE = "60s"


# Big5 常用字區（5401 字）。台灣繁體文字幾乎只用這一區，這區的字一律不改。
_COMMON_BIG5 = range(0xA440, 0xC67F)

# 只收錄在台灣沒有其他常見意思的大陸用語；「優化」「支持」「數據」等不列入
_TERMS = {
    "視頻": "影片", "音頻": "音訊", "實時": "即時", "代碼": "程式碼", "信號": "訊號",
    "信息": "資訊", "網絡": "網路", "數據集": "資料集", "魯棒性": "穩健性", "算法": "演算法",
}
# 「演算法」裡本來就有「算法」，前面是「演」時不替換
_TERM_RE = re.compile("|".join(
    ("(?<!演)算法" if term == "算法" else term)
    for term in sorted(_TERMS, key=len, reverse=True)
))

_converter: opencc.OpenCC | None = None


def _is_common(ch: str) -> bool:
    try:
        code = ch.encode("cp950")
    except UnicodeEncodeError:
        return False
    return len(code) == 2 and int.from_bytes(code, "big") in _COMMON_BIG5


def to_taiwan(text: str) -> str:
    """修正模型偶爾混入的簡體字與大陸用語。

    OpenCC 的詞組規則套在已經是繁體的文字上會誤改（文件→檔案、干擾→幹擾），
    所以只逐字轉換常用字以外的字，且轉換結果必須是常用字。
    """
    global _converter
    if _converter is None:
        _converter = opencc.OpenCC("s2tw")
    chars = []
    for ch in text:
        if "\u4e00" <= ch <= "\u9fff" and not _is_common(ch):
            converted = _converter.convert(ch)
            if converted != ch and all(_is_common(c) for c in converted):
                ch = converted
        chars.append(ch)
    return _TERM_RE.sub(lambda m: _TERMS[m.group(0)], "".join(chars))


class TranslationError(RuntimeError):
    """翻譯失敗：連線、逾時、回應錯誤或回傳格式不符。"""


@dataclass(frozen=True)
class Translation:
    title_zh: str
    summary_zh: str


def _clean(text: str | None) -> str:
    return " ".join((text or "").split())


class OllamaTranslator:
    """呼叫 Ollama 的 /api/chat 翻譯一篇論文。"""

    def __init__(
        self,
        model: str,
        url: str,
        timeout: float,
        session: requests.Session | None = None,
    ):
        self.model = model
        self.url = url
        self.timeout = timeout
        self.session = session or requests.Session()

    def translate(self, title: str, summary: str) -> Translation:
        payload = {
            "model": self.model,
            "stream": False,
            "think": False,
            "keep_alive": KEEP_ALIVE,
            "format": RESPONSE_SCHEMA,
            "options": {"temperature": 0.2, "num_ctx": 4096},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"標題：{_clean(title)}\n\n摘要：{_clean(summary)}"},
            ],
        }
        try:
            response = self.session.post(f"{self.url}/api/chat", json=payload, timeout=self.timeout)
        except Exception as exc:
            raise TranslationError(f"無法連線 Ollama（{self.url}）：{exc}") from None
        if response.status_code != 200:
            raise TranslationError(f"Ollama 回應 {response.status_code}")

        try:
            content = json.loads(response.json()["message"]["content"])
            result = Translation(
                to_taiwan(_clean(content["title_zh"])),
                to_taiwan(_clean(content["summary_zh"])),
            )
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise TranslationError(f"Ollama 回傳格式不符：{exc}") from None
        if not result.title_zh or not result.summary_zh:
            raise TranslationError("Ollama 回傳的翻譯是空的")
        return result
