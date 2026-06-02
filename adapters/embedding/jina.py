import logging

import requests
from django.conf import settings

from core.exceptions import EmbeddingError

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.jina.ai/v1/embeddings"


class JinaEmbeddingAdapter:
    def __init__(self) -> None:
        self._api_key = settings.JINA_API_KEY
        self._model = settings.EMBEDDING_MODEL

    def embed(self, text: str, task: str = "retrieval.query") -> list[float]:
        try:
            response = requests.post(
                _BASE_URL,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self._model,
                    "input": [text],
                    "task": task,
                },
                timeout=30,
            )
            response.raise_for_status()
        except requests.RequestException as e:
            logger.error("EMBED | Jina request failed: %s", e)
            raise EmbeddingError(str(e)) from e

        return response.json()["data"][0]["embedding"]
