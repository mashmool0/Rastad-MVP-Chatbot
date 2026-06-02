import logging

from django.db import connection

from apps.knowledge.models import KnowledgeChunk
from core.types import RetrievedChunk

logger = logging.getLogger(__name__)


class KnowledgeRepository:
    def get_existing(self, source_file: str, chunk_index: int) -> KnowledgeChunk | None:
        return KnowledgeChunk.objects.filter(
            source_file=source_file, chunk_index=chunk_index
        ).first()

    def upsert(
            self,
            source_file: str,
            chunk_index: int,
            content: str,
            content_hash: str,
            embedding: list[float],
    ) -> None:
        KnowledgeChunk.objects.update_or_create(
            source_file=source_file,
            chunk_index=chunk_index,
            defaults={
                "content": content,
                "content_hash": content_hash,
                "embedding": embedding,
            },
        )

    def similarity_search(self, vector: list[float], top_k: int) -> list[RetrievedChunk]:
        # Raw SQL for pgvector cosine similarity — ORM doesn't support <=> natively
        sql = """
            SELECT content, source_file, chunk_index,
                   1 - (embedding <=> %s::vector) AS similarity
            FROM knowledge_chunks
            ORDER BY embedding <=> %s::vector
            LIMIT %s
        """
        with connection.cursor() as cursor:
            cursor.execute(sql, [str(vector), str(vector), top_k])
            rows = cursor.fetchall()

        return [
            RetrievedChunk(
                content=row[0],
                source_file=row[1],
                chunk_index=row[2],
                similarity=float(row[3]),
            )
            for row in rows
        ]
