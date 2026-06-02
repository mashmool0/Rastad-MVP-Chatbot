import logging

from django.conf import settings

from core.exceptions import EmbeddingError
from core.ports import EmbeddingPort
from core.types import RetrievedChunk
from repositories.knowledge_repository import KnowledgeRepository

logger = logging.getLogger(__name__)


class RetrieverService:
    def __init__(self, embedder: EmbeddingPort, knowledge_repo: KnowledgeRepository) -> None:
        self._embedder = embedder
        self._knowledge_repo = knowledge_repo

    def retrieve(self, message: str) -> list[RetrievedChunk]:
        try:
            vector = self._embedder.embed(message, task="retrieval.query")
        except EmbeddingError as e:
            logger.warning("FALLBACK | embedding failed — skipping retrieval: %s", e)
            return []

        chunks = self._knowledge_repo.similarity_search(vector, top_k=settings.RETRIEVE_TOP_K)
        top = max((c.similarity for c in chunks), default=0.0)
        logger.info("RETRIEVE | top_similarity=%.2f chunks=%d", top, len(chunks))
        return chunks
