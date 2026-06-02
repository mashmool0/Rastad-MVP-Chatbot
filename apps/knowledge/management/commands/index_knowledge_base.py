import hashlib
import logging
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from adapters.factory import get_embedder
from repositories.knowledge_repository import KnowledgeRepository

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Embed knowledge_base/*.txt files into pgvector (idempotent)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Re-embed every chunk, ignoring the content_hash skip",
        )

    def handle(self, *args, **options):
        kb_dir = Path(settings.BASE_DIR) / "knowledge_base"
        repo = KnowledgeRepository()
        embedder = get_embedder()
        force = options["force"]

        total = indexed = skipped = 0

        for txt_file in sorted(kb_dir.glob("*.txt")):
            raw = txt_file.read_text(encoding="utf-8")
            paragraphs = [p.strip() for p in raw.split("\n\n")]
            chunks = [p for p in paragraphs if len(p) >= 20]

            for chunk_index, content in enumerate(chunks):
                total += 1
                content_hash = hashlib.md5(content.encode()).hexdigest()

                existing = repo.get_existing(txt_file.name, chunk_index)
                if not force and existing and existing.content_hash == content_hash:
                    skipped += 1
                    continue

                embedding = embedder.embed(content, task="retrieval.passage")
                repo.upsert(
                    source_file=txt_file.name,
                    chunk_index=chunk_index,
                    content=content,
                    content_hash=content_hash,
                    embedding=embedding,
                )
                indexed += 1
                logger.debug("BOOT | indexed %s §%d", txt_file.name, chunk_index)

        logger.info(
            "BOOT | Knowledge base indexed — %d new, %d unchanged, %d total chunks",
            indexed, skipped, total,
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Done: {indexed} indexed, {skipped} skipped (unchanged), {total} total"
            )
        )
