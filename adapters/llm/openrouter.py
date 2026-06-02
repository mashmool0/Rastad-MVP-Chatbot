import json
import logging
import re

import requests
from django.conf import settings
from pydantic import ValidationError

from core.exceptions import LLMError
from core.types import ClassificationResult

logger = logging.getLogger(__name__)

_BASE_URL = "https://openrouter.ai/api/v1/chat/completions"
_MAX_RETRIES = 2

_CLASSIFY_SYSTEM = """تو یک سیستم دسته‌بندی هوشمند برای پشتیبانی کاربران راستاد هستی.
راستاد یک پلتفرم تخصصی ارز دیجیتال با بیش از ۵۴۴ هزار دنبال‌کننده است که خدمات سیگنال، تحلیل، اشتراک VIP، برنامه KOL و معرفی صرافی ارائه می‌دهد.
پیام کاربر را تحلیل کن و دقیقاً یک JSON با این ساختار برگردان:

{
  "intent": "<یکی از مقادیر مجاز>",
  "segment": "<یکی از مقادیر مجاز>",
  "needs_human_support": <true یا false>
}

مقادیر مجاز برای intent:
- vip_question: سوال درباره خدمات VIP
- exchange_registration: ثبت‌نام یا سوال درباره صرافی
- kol_collaboration: همکاری به عنوان KOL
- support_request: مشکل فنی، پرداخت، یا نیاز به پشتیبانی
- general_info: سوال اطلاعاتی عمومی
- unknown: پیام نامفهوم یا خارج از موضوع

مقادیر مجاز برای segment:
- new_user: کاربر جدید بدون سابقه
- vip_interest: علاقه‌مند به خدمات VIP
- exchange_signup: در حال ثبت‌نام در صرافی
- kol_candidate: داوطلب همکاری KOL
- support_needed: نیاز به پشتیبانی فوری
- general_question: سوال عمومی

needs_human_support = true اگر:
- مشکل پرداخت یا فنی گزارش شده
- پیام عصبانی یا اضطراری است
- موضوع خارج از دانش سیستم است

فقط JSON برگردان. بدون توضیح اضافه."""

_GENERATE_SYSTEM = """تو دستیار هوشمند پشتیبانی راستاد هستی.
راستاد یک پلتفرم تخصصی ارز دیجیتال است با کانال تلگرام @RastadCo (۵۴۴ هزار عضو)، اشتراک VIP، خدمات Trade Assist، برنامه KOL و معرفی صرافی.
سایت رسمی: smrastad.com | پشتیبانی: @Rastad_support | ربات: @Rastad_bot
بر اساس اطلاعات زیر به کاربر پاسخ بده.
پاسخ باید:
- فارسی و محترمانه باشد
- فقط از اطلاعات داده‌شده استفاده کند
- کوتاه و مستقیم باشد (حداکثر ۳ جمله)
- اگر اطلاعات کافی نداری، بگو تیم پشتیبانی کمک می‌کند"""

_RETRY_TEMPLATE = """خطای قبلی: {error}
مقادیر مجاز برای intent: vip_question, exchange_registration, kol_collaboration, support_request, general_info, unknown
مقادیر مجاز برای segment: new_user, vip_interest, exchange_signup, kol_candidate, support_needed, general_question
فقط یک JSON معتبر برگردان. هیچ متن اضافه‌ای نداشته باش.

پیام کاربر: {message}"""


def _extract_json(text: str) -> str:
    # Strip Qwen3 thinking blocks before parsing
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    # Extract first JSON object, handles markdown code fences too
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        return match.group(0)
    return text


class OpenRouterLLMAdapter:
    def __init__(self) -> None:
        self._api_key = settings.LLM_API_KEY
        self._model = settings.LLM_MODEL

    def _chat(self, user_content: str, system: str = "") -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user_content})

        try:
            response = requests.post(
                _BASE_URL,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={"model": self._model, "messages": messages},
                timeout=30,
            )
            response.raise_for_status()
        except requests.RequestException as e:
            logger.error("LLM | OpenRouter request failed: %s", e)
            raise LLMError(str(e)) from e

        return response.json()["choices"][0]["message"]["content"]

    def classify(self, message: str) -> ClassificationResult:
        error_context = ""
        for attempt in range(_MAX_RETRIES + 1):
            if attempt == 0:
                user_content = message
                system = _CLASSIFY_SYSTEM
            else:
                user_content = _RETRY_TEMPLATE.format(error=error_context, message=message)
                system = _CLASSIFY_SYSTEM

            try:
                raw = self._chat(user_content, system=system)
                data = json.loads(_extract_json(raw))
                result = ClassificationResult(**data)
                return result
            except (json.JSONDecodeError, ValidationError, KeyError) as e:
                error_context = str(e)
                logger.warning("CLASSIFY | attempt %d failed: %s", attempt + 1, e)
            except LLMError:
                raise

        raise LLMError(f"classification failed after {_MAX_RETRIES} retries")

    def generate_reply(self, message: str, chunks: list[str], intent: str) -> str:
        context = "\n\n".join(chunks) if chunks else ""
        user_content = (
            f"--- اطلاعات راستاد ---\n{context}\n----------------------\n\n"
            f"نوع درخواست: {intent}\n\n"
            f"پیام کاربر: {message}"
        )
        return self._chat(user_content, system=_GENERATE_SYSTEM)
