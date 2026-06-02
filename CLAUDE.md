# Rastad Project — Claude Coding Rules

Read this file before writing any code. These rules apply to every file in this project.

---

## Architecture — Layer Law (never skip)

```
API View → Service → Repository → DB
API View → Service → Adapter    → External API
```

- Views have zero logic — call one service method, return its result.
- Services never import from `adapters/`, `requests`, `openai`, `httpx`, or any ORM directly.
- Repositories never call adapters. Adapters never call repositories.
- A layer only knows the layer directly below it.

---

## Logging — always use the project logger, always use the prefix format

Import and use the module-level logger. Never use `print()`.

```python
import logging
logger = logging.getLogger(__name__)
```

Every log line must carry one of these prefixes so Docker logs are scannable:

| Prefix | When |
|---|---|
| `BOOT` | startup / KB indexing |
| `REQUEST` | incoming message received |
| `CLASSIFY` | after classification step |
| `RETRIEVE` | after retrieval step |
| `EVALUATE` | after evaluation step |
| `GENERATE` | after generation step |
| `DONE` | pipeline complete |
| `FALLBACK` | fallback path triggered |

Format: `logger.info("CLASSIFY | intent=%s segment=%s", intent, segment)`

Log levels:
- `INFO` — normal flow, every pipeline step on success
- `WARNING` — degraded but handled (fallback triggered, low confidence)
- `ERROR` — external failure (LLM down, DB error, embedding error)
- `CRITICAL` — startup failure

**Never log message content above DEBUG level.** Only metadata (user_id, intent, latency, etc.).

---

## Adapters — always wrap HTTP in try/except, always raise domain errors

```python
try:
    response = requests.post(...)
    response.raise_for_status()
except requests.RequestException as e:
    logger.error("LLM | request failed: %s", e)
    raise LLMError(str(e)) from e
```

Import domain exceptions from `core/exceptions.py`. Never let `requests.RequestException`
or `httpx.*` propagate to the service layer.

---

## Services — always degrade gracefully, never fail the user response

```python
try:
    chunks = self.retriever.retrieve(message)
except EmbeddingError:
    logger.warning("FALLBACK | embedding failed — skipping retrieval")
    chunks = []
```

A DB write failure must be caught, logged at ERROR, and the reply still returned.
A pipeline step failure must trigger its documented fallback — never a 500.

---

## Types — use the domain types, never raw dicts

- `ClassificationResult` (pydantic, from `core/types.py`) — never pass `intent` as a raw string between layers.
- `RetrievedChunk` (dataclass, from `core/types.py`) — never pass raw DB rows up to services.
- `PipelineResult` (dataclass) — the single object the API view receives from the pipeline.

---

## Comments — write almost none

Only comment when the WHY is non-obvious: a hidden constraint, a workaround, a threshold rationale.
Never comment what the code does — names do that.

Exception: every module may have one line at the top stating its layer role if ambiguous.

---

## No magic numbers

All thresholds, dimensions, and limits come from Django settings, which load from `.env`:

```python
from django.conf import settings
threshold = settings.CONFIDENCE_THRESHOLD   # not 0.45
top_k     = settings.RETRIEVE_TOP_K         # not 4
dim       = settings.EMBEDDING_DIM          # not 1024
```

---

## Dependency injection — services receive adapters as constructor args

```python
# correct
class ClassifierService:
    def __init__(self, llm: LLMPort):
        self.llm = llm

# wrong — never instantiate an adapter inside a service
class ClassifierService:
    def __init__(self):
        self.llm = OpenRouterLLMAdapter()
```

Adapters are wired in `adapters/factory.py` and injected at app startup.

---

## Env vars — single source of truth

All env vars are defined in `.env.example`. The canonical list:

```
LLM_API_KEY         # OpenRouter sk-or-v1-…
LLM_PROVIDER        # openrouter | mock
LLM_MODEL           # qwen/qwen3-8b
JINA_API_KEY        # Jina AI embedding key
EMBEDDING_MODEL     # jina-embeddings-v3
EMBEDDING_DIM       # 1024
CONFIDENCE_THRESHOLD # 0.45
RETRIEVE_TOP_K      # 4
DB_NAME / DB_USER / DB_PASSWORD / DB_HOST / DB_PORT
SECRET_KEY
DEBUG
```

Never hardcode values that belong in `.env`. Never commit `.env`.

---

## Testing — mock LLM + stub embedder, never hit real APIs in tests

- `LLM_PROVIDER=mock` in `pytest.ini` / `conftest.py` env overrides.
- Use a `MockEmbeddingAdapter` that returns a fixed `list[float]` of length 1024.
- Tests must not make network calls. If a test fails because of a missing API key, it is written wrong.

---

## File layout — follow the spec exactly

```
rastad/          ← Django project (settings, urls, wsgi)
apps/            ← Django apps (api, users, messages, knowledge)
core/            ← ports.py, types.py, exceptions.py
services/        ← pipeline, classifier, retriever, evaluator, generator
repositories/    ← user, message, knowledge
adapters/        ← llm/ (openrouter, mock), embedding/ (jina), factory.py
knowledge_base/  ← *.txt source files (do not modify)
docs/            ← specs (do not modify during coding)
```

No file should be created outside this layout without a stated reason.

---

## Build order (follow when starting a new session mid-build)

1. Skeleton & config (`requirements.txt`, `manage.py`, settings)
2. Core domain (`core/types.py`, `core/ports.py`, `core/exceptions.py`)
3. Models & migrations (users, messages, knowledge + pgvector migrations)
4. Repositories
5. Adapters (openrouter LLM, mock LLM, jina embedding, factory)
6. Services (classifier → retriever → evaluator → generator → pipeline)
7. KB indexing management command
8. API layer (serializers, views, urls)
9. Logging configuration
10. Tests
