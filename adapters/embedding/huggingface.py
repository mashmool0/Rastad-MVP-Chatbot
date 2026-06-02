import logging
import time

import requests
from django.conf import settings

from core.exceptions import EmbeddingError

logger = logging.getLogger(__name__)

_BASE_URL = "https://api-inference.huggingface.co/models"
_MAX_WAIT_RETRIES = 3  # HuggingFace free tier cold-starts → model loading → retry


class HuggingFaceEmbeddingAdapter:
    def __init__(self) -> None:
        self._api_key = settings.HUGGINGFACE_API_KEY
        self._model = settings.EMBEDDING_MODEL
        self._url = f"{_BASE_URL}/{self._model}"

    def embed(self, text: str, task: str = "retrieval.query") -> list[float]:
        # multilingual-e5 requires explicit prefixes for asymmetric retrieval
        prefix = "query: " if task == "retrieval.query" else "passage: "
        prefixed = prefix + text

        for attempt in range(_MAX_WAIT_RETRIES):
            try:
                response = requests.post(
                    self._url,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "inputs": prefixed,
                        "options": {"wait_for_model": True},
                    },
                    timeout=60,  # longer timeout — free tier cold starts can take 20–30s
                )

                # model still loading on free tier
                if response.status_code == 503:
                    wait = response.json().get("estimated_time", 10)
                    logger.warning("EMBED | HuggingFace model loading, waiting %.0fs (attempt %d)", wait, attempt + 1)
                    time.sleep(min(wait, 20))
                    continue

                response.raise_for_status()

            except requests.RequestException as e:
                logger.error("EMBED | HuggingFace request failed: %s", e)
                raise EmbeddingError(str(e)) from e

            result = response.json()

            # feature-extraction returns [[float, ...]] for a single input
            if isinstance(result, list) and result and isinstance(result[0], list):
                return result[0]
            if isinstance(result, list) and result and isinstance(result[0], float):
                return result

            logger.error("EMBED | unexpected response shape: %s", type(result))
            raise EmbeddingError(f"unexpected embedding response shape: {type(result)}")

        raise EmbeddingError(f"HuggingFace model still loading after {_MAX_WAIT_RETRIES} retries")
