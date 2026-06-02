import logging

from core.exceptions import LLMError
from core.ports import LLMPort
from core.types import RetrievedChunk

logger = logging.getLogger(__name__)

_HANDOFF_REPLY = (
    "متأسفم، در حال حاضر اطلاعات کافی برای پاسخ به این سوال ندارم.\n"
    "تیم پشتیبانی راستاد در اسرع وقت با شما تماس می‌گیرد."
)


class GeneratorService:
    def __init__(self, llm: LLMPort) -> None:
        self._llm = llm

    def generate(
        self,
        message: str,
        chunks: list[RetrievedChunk],
        intent: str,
        needs_human: bool,
    ) -> tuple[str, bool]:
        """Return (reply, fallback_used)."""
        if needs_human and not chunks:
            return _HANDOFF_REPLY, False

        chunk_texts = [c.content for c in chunks]

        try:
            reply = self._llm.generate_reply(message, chunk_texts, intent)
            logger.info("GENERATE | llm_provider=%s", "openrouter")
            return reply, False
        except LLMError as e:
            logger.warning("FALLBACK | LLM generate failed — using template reply: %s", e)
            fallback = chunks[0].content if chunks else _HANDOFF_REPLY
            return fallback, True
