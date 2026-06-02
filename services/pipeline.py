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
        start = time.monotonic()
        logger.info("REQUEST | user_id=%s message_len=%d", user_id, len(message))

        # 2a — resolve user
        user = self._user_repo.get_or_create(user_id, name)

        # 2b — classify
        classification = self._classifier.classify(message)

        # 2c — retrieve
        chunks = self._retriever.retrieve(message)

        # 2d — evaluate
        needs_human, max_similarity = self._evaluator.evaluate(chunks, classification)

        # 2e — generate
        reply, fallback_used = self._generator.generate(
            message, chunks, classification.intent, needs_human
        )

        latency_ms = int((time.monotonic() - start) * 1000)
        chunks_used = [f"{c.source_file} §{c.chunk_index}" for c in chunks]

        confidence_label = (
            "HIGH" if max_similarity >= 0.7
            else "MEDIUM" if max_similarity >= settings.CONFIDENCE_THRESHOLD
            else "LOW"
        )

        # Structured per-request payload — no message content logged
        structured = {
            "timestamp":           datetime.now(timezone.utc).isoformat(),
            "user_id":             str(user.user_id),
            "intent":              classification.intent,
            "segment":             classification.segment,
            "needs_human_support": needs_human,
            "confidence":          confidence_label,
            "top_chunk_similarity": round(max_similarity, 4),
            "chunks_used":         chunks_used,
            "llm_provider":        settings.LLM_PROVIDER,
            "fallback_used":       fallback_used,
            "latency_ms":          latency_ms,
            "error":               None,
        }
        logger.info("DONE | user_id=%s total_ms=%d payload=%s",
                    user.user_id, latency_ms,
                    json.dumps(structured, ensure_ascii=False))

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

        return PipelineResult(
            reply=reply,
            intent=classification.intent,
            user_segment=classification.segment,
            needs_human_support=needs_human,
            confidence=round(max_similarity, 4),
            chunks_used=chunks_used,
            llm_provider=settings.LLM_PROVIDER,
            fallback_used=fallback_used,
            latency_ms=latency_ms,
        )
