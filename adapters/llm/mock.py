from core.types import ClassificationResult

_CLASSIFICATIONS: dict[str, ClassificationResult] = {
    "vip":      ClassificationResult(intent="vip_question",          segment="vip_interest",    needs_human_support=False),
    "صرافی":    ClassificationResult(intent="exchange_registration",  segment="exchange_signup", needs_human_support=False),
    "kol":      ClassificationResult(intent="kol_collaboration",      segment="kol_candidate",   needs_human_support=False),
    "مشکل":     ClassificationResult(intent="support_request",        segment="support_needed",  needs_human_support=True),
    "پرداخت":   ClassificationResult(intent="support_request",        segment="support_needed",  needs_human_support=True),
    "همکاری":   ClassificationResult(intent="kol_collaboration",      segment="kol_candidate",   needs_human_support=False),
    "ثبت":      ClassificationResult(intent="exchange_registration",  segment="exchange_signup", needs_human_support=False),
}

_DEFAULT = ClassificationResult(intent="general_info", segment="general_question", needs_human_support=False)

_REPLIES: dict[str, str] = {
    "vip_question":          "خدمات VIP راستاد شامل تحلیل‌های اختصاصی و مدیر اکانت است.",
    "exchange_registration": "برای ثبت‌نام در صرافی به بخش ثبت‌نام مراجعه کنید.",
    "kol_collaboration":     "برنامه KOL راستاد برای اینفلوئنسرها مزایای ویژه دارد.",
    "support_request":       "تیم پشتیبانی راستاد در اسرع وقت با شما تماس می‌گیرد.",
    "general_info":          "راستاد یک پلتفرم جامع برای معامله‌گران ارز دیجیتال است.",
}


class MockLLMAdapter:
    def classify(self, message: str) -> ClassificationResult:
        lower = message.lower()
        for keyword, result in _CLASSIFICATIONS.items():
            if keyword in lower or keyword in message:
                return result
        return _DEFAULT

    def generate_reply(self, message: str, chunks: list[str], intent: str) -> str:
        return _REPLIES.get(intent, _REPLIES["general_info"])
