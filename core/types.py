from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel


class ClassificationResult(BaseModel):
    intent: Literal[
        "vip_question",
        "exchange_registration",
        "kol_collaboration",
        "support_request",
        "general_info",
        "unknown",
    ]
    segment: Literal[
        "new_user",
        "vip_interest",
        "exchange_signup",
        "kol_candidate",
        "support_needed",
        "general_question",
    ]
    needs_human_support: bool


@dataclass
class RetrievedChunk:
    content: str
    source_file: str
    chunk_index: int
    similarity: float


@dataclass
class PipelineResult:
    reply: str
    intent: str
    user_segment: str
    needs_human_support: bool
    confidence: float
    chunks_used: list[str]
    llm_provider: str
    fallback_used: bool
    latency_ms: int        # total end-to-end
    llm_ms: int = 0        # classify + generate combined
    embedding_ms: int = 0  # Jina embed + pgvector search
    other_ms: int = 0      # user lookup + evaluation + DB write
    error: str | None = None
