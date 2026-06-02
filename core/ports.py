from typing import Protocol

from core.types import ClassificationResult


class LLMPort(Protocol):
    def classify(self, message: str) -> ClassificationResult: ...
    def generate_reply(self, message: str, chunks: list[str], intent: str) -> str: ...


class EmbeddingPort(Protocol):
    def embed(self, text: str, task: str = "retrieval.query") -> list[float]: ...
