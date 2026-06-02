from django.conf import settings

from core.types import ClassificationResult, RetrievedChunk


class EvaluatorService:
    def evaluate(
        self,
        chunks: list[RetrievedChunk],
        classification: ClassificationResult,
    ) -> tuple[bool, float, list[str]]:
        """Return (needs_human_support, max_similarity, reasons)."""
        max_similarity = max((c.similarity for c in chunks), default=0.0)

        reasons = []
        if max_similarity < settings.CONFIDENCE_THRESHOLD:
            reasons.append("low_confidence")
        if classification.intent == "support_request":
            reasons.append("support_request_intent")
        if classification.needs_human_support:
            reasons.append("llm_flagged")

        needs_human = bool(reasons)
        return needs_human, max_similarity, reasons
