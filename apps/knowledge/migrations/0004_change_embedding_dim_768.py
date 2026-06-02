from django.db import migrations


class Migration(migrations.Migration):
    """
    Migrates embedding column from vector(1024) — Jina jina-embeddings-v3 —
    to vector(768) — HuggingFace intfloat/multilingual-e5-base.

    Old embeddings are incompatible with the new model so all chunks are
    deleted. The management command 'index_knowledge_base' will re-embed
    everything on next startup (idempotent, safe to run repeatedly).
    """

    dependencies = [("knowledge", "0003_add_vector_index")]

    operations = [
        migrations.RunSQL(
            sql="""
                -- drop the approximate-search index first (required before column type change)
                DROP INDEX IF EXISTS idx_chunk_embedding_ivfflat;

                -- old embeddings are 1024-dim and invalid for the new 768-dim model
                TRUNCATE TABLE knowledge_chunks;

                -- change column type from vector(1024) to vector(768)
                ALTER TABLE knowledge_chunks
                    ALTER COLUMN embedding TYPE vector(768);

                -- recreate the ivfflat index for the new dimension
                CREATE INDEX IF NOT EXISTS idx_chunk_embedding_ivfflat
                    ON knowledge_chunks
                    USING ivfflat (embedding vector_cosine_ops)
                    WITH (lists = 10);
            """,
            reverse_sql="""
                DROP INDEX IF EXISTS idx_chunk_embedding_ivfflat;
                TRUNCATE TABLE knowledge_chunks;
                ALTER TABLE knowledge_chunks
                    ALTER COLUMN embedding TYPE vector(1024);
                CREATE INDEX IF NOT EXISTS idx_chunk_embedding_ivfflat
                    ON knowledge_chunks
                    USING ivfflat (embedding vector_cosine_ops)
                    WITH (lists = 10);
            """,
        )
    ]
