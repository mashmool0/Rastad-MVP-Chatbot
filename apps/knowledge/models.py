from django.conf import settings
from django.db import models
from pgvector.django import VectorField


class KnowledgeChunk(models.Model):
    source_file = models.CharField(max_length=255)
    chunk_index = models.IntegerField()
    content = models.TextField()
    content_hash = models.CharField(max_length=32)
    embedding = VectorField(dimensions=settings.EMBEDDING_DIM)

    class Meta:
        db_table = "knowledge_chunks"
        unique_together = [("source_file", "chunk_index")]
        indexes = [
            models.Index(fields=["source_file", "chunk_index"], name="idx_chunk_lookup"),
        ]

    def __str__(self):
        return f"{self.source_file}:chunk_{self.chunk_index}"
