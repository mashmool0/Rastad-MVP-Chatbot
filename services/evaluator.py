import logging

from django.conf import settings

from core.types import ClassificationResult, RetrievedChunk

logger = logging.getLogger(__name__)


class EvaluatorService:
    def evaluate(
        self,
        chunks: list[RetrievedChunk],
        classification: ClassificationResult,
    ) -> tuple[bool, float]:
        """Return (needs_human_support, max_similarity)."""
        max_similarity = max((c.similarity for c in chunks), default=0.0)

        low_confidence = max_similarity < settings.CONFIDENCE_THRESHOLD
        is_support = classification.intent == "support_request"
        llm_flagged = classification.needs_human_support

        needs_human = low_confidence or is_support or llm_flagged

        if needs_human:
            logger.warning(
                "EVALUATE | needs_human_support=True confidence=%s similarity=%.2f",
                "LOW" if low_confidence else "OK",
                max_similarity,
            )
        else:
            confidence = "HIGH" if max_similarity >= 0.7 else "MEDIUM"
            logger.info("EVALUATE | needs_human_support=False confidence=%s similarity=%.2f",
                        confidence, max_similarity)

        return needs_human, max_similarity
