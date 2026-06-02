import json
import logging
import time
from datetime import datetime, timezone

from django.conf import settings

from core.types import PipelineResult
from repositories.knowledge_repository import KnowledgeRepository
from repositories.message_repository import MessageRepository
from repositories.user_repository import UserRepository
from services.classifier import ClassifierService
from services.evaluator import EvaluatorService
from services.generator import GeneratorService
from services.retriever import RetrieverService

logger = logging.getLogger(__name__)


def _ms(start: float, end: float) -> int:
    return int((end - start) * 1000)


class MessagePipeline:
    def __init__(
        self,
        classifier: ClassifierService,
        retriever: RetrieverService,
        evaluator: EvaluatorService,
        generator: GeneratorService,
        user_repo: UserRepository,
        message_repo: MessageRepository,
        knowledge_repo: KnowledgeRepository,
    ) -> None:
        self._classifier = classifier
        self._retriever = retriever
        self._evaluator = evaluator
        self._generator = generator
        self._user_repo = user_repo
        self._message_repo = message_repo
        self._knowledge_repo = knowledge_repo

    def process(self, user_id: int | None, name: str, message: str) -> PipelineResult:
        t0 = time.monotonic()
        logger.info("REQUEST | user_id=%s message_len=%d", user_id, len(message))

        # 2a — user lookup
        user = self._user_repo.get_or_create(user_id, name)
        t_user = time.monotonic()

        # 2b — classify (LLM call 1)
        classification = self._classifier.classify(message)
        t_classify = time.monotonic()
        logger.info("CLASSIFY | intent=%s latency_ms=%d", classification.intent, _ms(t_user, t_classify))

        # 2c — embed + retrieve (Jina + pgvector)
        chunks = self._retriever.retrieve(message)
        t_retrieve = time.monotonic()
        logger.info("RETRIEVE | chunks=%d latency_ms=%d", len(chunks), _ms(t_classify, t_retrieve))

        # 2d — evaluate
        needs_human, max_similarity = self._evaluator.evaluate(chunks, classification)
        t_evaluate = time.monotonic()

        # 2e — generate (LLM call 2)
        reply, fallback_used = self._generator.generate(
            message, chunks, classification.intent, needs_human
        )
        t_generate = time.monotonic()
        logger.info("GENERATE | latency_ms=%d", _ms(t_evaluate, t_generate))

        # Break down the three timing buckets
        llm_ms       = _ms(t_user, t_classify) + _ms(t_evaluate, t_generate)
        embedding_ms = _ms(t_classify, t_retrieve)
        other_ms     = _ms(t0, t_user) + _ms(t_retrieve, t_evaluate)

        chunks_used = [f"{c.source_file} §{c.chunk_index}" for c in chunks]
        confidence_label = (
            "HIGH"   if max_similarity >= 0.7
            else "MEDIUM" if max_similarity >= settings.CONFIDENCE_THRESHOLD
            else "LOW"
        )

        # Structured per-request payload — no message content logged
        structured = {
            "timestamp":            datetime.now(timezone.utc).isoformat(),
            "user_id":              str(user.user_id),
            "intent":               classification.intent,
            "segment":              classification.segment,
            "needs_human_support":  needs_human,
            "confidence":           confidence_label,
            "top_chunk_similarity": round(max_similarity, 4),
            "chunks_used":          chunks_used,
            "llm_provider":         settings.LLM_PROVIDER,
            "fallback_used":        fallback_used,
            "latency_breakdown": {
                "llm_ms":       llm_ms,
                "embedding_ms": embedding_ms,
                "other_ms":     other_ms,
            },
            "error": None,
        }
        logger.info(
            "DONE | llm_ms=%d embedding_ms=%d other_ms=%d total_ms=%d",
            llm_ms, embedding_ms, other_ms, llm_ms + embedding_ms + other_ms,
        )
        logger.debug("DONE | payload=%s", json.dumps(structured, ensure_ascii=False))

        # 2f — persist (never fail the response on a storage error)
        try:
            self._message_repo.save(
                user=user,
                user_message=message,
                assistant_reply=reply,
                intent=classification.intent,
                needs_human_support=needs_human,
            )
            self._user_repo.update_last_seen_and_segment(user, classification.segment)
        except Exception as e:
            logger.error("DB | failed to save message: %s", e)

        total_ms = _ms(t0, time.monotonic())

        return PipelineResult(
            reply=reply,
            intent=classification.intent,
            user_segment=classification.segment,
            needs_human_support=needs_human,
            confidence=round(max_similarity, 4),
            chunks_used=chunks_used,
            llm_provider=settings.LLM_PROVIDER,
            fallback_used=fallback_used,
            latency_ms=total_ms,
            llm_ms=llm_ms,
            embedding_ms=embedding_ms,
            other_ms=other_ms,
        )
