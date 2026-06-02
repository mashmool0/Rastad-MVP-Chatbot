import logging

from core.exceptions import LLMError
from core.ports import LLMPort
from core.types import ClassificationResult

logger = logging.getLogger(__name__)

# Persian + English keywords → (intent, segment)
_KEYWORD_MAP: list[tuple[str, str, str]] = [
    ("vip",     "vip_question",          "vip_interest"),
    ("صرافی",   "exchange_registration", "exchange_signup"),
    ("kol",     "kol_collaboration",     "kol_candidate"),
    ("مشکل",    "support_request",       "support_needed"),
    ("پرداخت",  "support_request",       "support_needed"),
    ("همکاری",  "kol_collaboration",     "kol_candidate"),
    ("ثبت",     "exchange_registration", "exchange_signup"),
    ("اشتراک",  "vip_question",          "vip_interest"),
]

_FALLBACK = ClassificationResult(
    intent="unknown",
    segment="general_question",
    needs_human_support=True,
)


class RuleBasedClassifier:
    def classify(self, message: str) -> ClassificationResult:
        lower = message.lower()
        for keyword, intent, segment in _KEYWORD_MAP:
            if keyword in lower or keyword in message:
                return ClassificationResult(
                    intent=intent,
                    segment=segment,
                    needs_human_support=(intent == "support_request"),
                )
        return _FALLBACK


class ClassifierService:
    def __init__(self, llm: LLMPort) -> None:
        self._llm = llm
        self._rule_based = RuleBasedClassifier()

    def classify(self, message: str) -> ClassificationResult:
        try:
            result = self._llm.classify(message)
            logger.info("CLASSIFY | intent=%s segment=%s needs_human=%s",
                        result.intent, result.segment, result.needs_human_support)
            return result
        except LLMError as e:
            logger.warning("FALLBACK | LLM classify failed — using rule-based classifier: %s", e)
            result = self._rule_based.classify(message)
            logger.info("CLASSIFY | intent=%s segment=%s (rule-based)",
                        result.intent, result.segment)
            return result
