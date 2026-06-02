from django.conf import settings


class MockEmbeddingAdapter:
    """Returns a zero vector of the configured dimension — no network calls."""

    def embed(self, text: str, task: str = "retrieval.query") -> list[float]:
        return [0.0] * settings.EMBEDDING_DIM
