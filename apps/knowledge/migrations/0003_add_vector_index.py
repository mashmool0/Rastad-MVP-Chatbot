from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("knowledge", "0002_initial")]

    operations = [
        migrations.RunSQL(
            sql="""
                CREATE INDEX IF NOT EXISTS idx_chunk_embedding_ivfflat
                ON knowledge_chunks
                USING ivfflat (embedding vector_cosine_ops)
                WITH (lists = 10);
            """,
            reverse_sql="DROP INDEX IF EXISTS idx_chunk_embedding_ivfflat;",
        )
    ]
