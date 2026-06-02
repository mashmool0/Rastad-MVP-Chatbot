# Architecture — Rastad AI Lead & Support Assistant

## 1. Overview

A monolithic Django application with strict internal layering.
No microservices, no message queues — one process, cleanly separated concerns.
The goal is a codebase that is easy to run, easy to explain, and easy to extend
without requiring a full rewrite.

The system handles one core flow: receive a user message → classify it →
retrieve relevant knowledge → generate a grounded reply → store everything →
return a structured response.

---

## 2. Layer Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     UI  (single HTML page)                   │
│          Tailwind CSS · desktop-first · served by Django     │
└──────────────────────────┬──────────────────────────────────┘
                           │ HTTP (JSON)
┌──────────────────────────▼──────────────────────────────────┐
│                      API Layer  (DRF)                        │
│  Views (no logic) · Serializers (validation) · URL routing  │
└──────────────────────────┬──────────────────────────────────┘
                           │ Python function calls
┌──────────────────────────▼──────────────────────────────────┐
│                    Service Layer                              │
│  MessagePipeline · ClassifierService · RetrieverService      │
│  GeneratorService · EvaluatorService                         │
└──────┬───────────────────────────────────────┬──────────────┘
       │                                       │
┌──────▼──────────────────┐   ┌───────────────▼──────────────┐
│    Repository Layer      │   │       Adapter Layer           │
│  UserRepository          │   │  LLMAdapter (OpenRouter)      │
│  MessageRepository       │   │  LLMAdapter (OpenAI)          │
│  KnowledgeRepository     │   │  LLMAdapter (Mock)            │
└──────┬──────────────────┘   │  EmbeddingAdapter (Jina AI)   │
       │                       │  EmbeddingAdapter (Mock)      │
┌──────▼──────────────────┐   └───────────────────────────────┘
│   PostgreSQL + pgvector  │
│  rastad_users · messages │
│  knowledge_chunks        │
└─────────────────────────┘
```

### Layer responsibilities

| Layer | Does | Does NOT |
|---|---|---|
| API | Receive HTTP, validate input, return HTTP | Any business logic |
| Service | Orchestrate steps, apply rules, make decisions | Touch DB directly or know about HTTP |
| Repository | All DB reads and writes | Business logic |
| Adapter | Wrap external APIs (LLM, embeddings) | Know about business domain |

No layer skips a level. A view never calls a repository. A repository never calls an adapter.

---

## 3. Request Flow — `POST /api/message`

```
Request: { user_id, name, message }
          │
          ▼
 [1] DRF Serializer
     — validate: message not empty (user_id optional, name defaults to "کاربر")
     — raise 400 if invalid
          │
          ▼
 [2] MessagePipeline.process(user_id, name, message)
     │
     ├─[2a] UserRepository.get_or_create(user_id, name)
     │       → if user_id given: get_or_create by PK
     │       → if no user_id: create new RastadUser (auth_user=None)
     │       → return RastadUser object
     │
     ├─[2b] ClassifierService.classify(message)          ← llm_ms starts
     │       → try: LLMAdapter.classify(message)
     │             _strip_thinking() → json.loads() → Pydantic validate
     │             → retry up to 2x with Persian error injection
     │       → fallback: RuleBasedClassifier.classify(message)
     │       → return ClassificationResult                ← llm classify done
     │
     ├─[2c] RetrieverService.retrieve(message)           ← embedding_ms starts
     │       → EmbeddingAdapter.embed(message, task="retrieval.query")
     │       → KnowledgeRepository.similarity_search(vector, top_k=4)
     │       → return list[RetrievedChunk] with similarity scores
     │                                                    ← embedding_ms ends
     ├─[2d] EvaluatorService.evaluate(chunks, classification)
     │       → max_similarity < CONFIDENCE_THRESHOLD (0.45)?
     │       → intent == "support_request"?
     │       → classification.needs_human_support from LLM?
     │       → return (needs_human: bool, max_similarity: float)
     │
     ├─[2e] GeneratorService.generate(message, chunks, intent, needs_human)
     │       → build prompt: system context + KB chunks + user message  ← llm_ms resumes
     │       → LLMAdapter.generate_reply() → _strip_thinking() → reply
     │       → fallback: best-matching chunk content or handoff template ← llm_ms ends
     │
     └─[2f] MessageRepository.save(...)
             UserRepository.update_last_seen_and_segment(...)
             → DB write errors logged, never fail the user response
          │
          ▼
 Response: {
   reply, intent, user_segment, needs_human_support, confidence,
   chunks_used, llm_provider, fallback_used,
   latency: { total_ms, llm_ms, embedding_ms, other_ms }
 }
```

---

## 4. Latency Breakdown

Every response includes a `latency` object with three buckets:

```json
"latency": {
  "total_ms": 2100,
  "llm_ms": 1750,
  "embedding_ms": 290,
  "other_ms": 60
}
```

| Field | Contains | High value means |
|---|---|---|
| `llm_ms` | classify call + generate call | LLM provider is slow or queued |
| `embedding_ms` | Jina API + pgvector search | Jina latency or cold connection |
| `other_ms` | User DB lookup + evaluation + DB write | DB is slow |

Logs on every request:
```
[INFO] CLASSIFY | intent=vip_question latency_ms=820
[INFO] RETRIEVE | chunks=4 latency_ms=290
[INFO] GENERATE | latency_ms=930
[INFO] DONE     | llm_ms=1750 embedding_ms=290 other_ms=60 total_ms=2100
```

---

## 5. LLMService — The Swappable Abstraction

All LLM and embedding calls go through protocol interfaces.
No service layer code ever imports `requests` or any provider SDK directly.

```python
# core/ports.py

class LLMPort(Protocol):
    def classify(self, message: str) -> ClassificationResult: ...
    def generate_reply(self, message: str, chunks: list[str], intent: str) -> str: ...

class EmbeddingPort(Protocol):
    def embed(self, text: str, task: str = "retrieval.query") -> list[float]: ...
```

```
adapters/llm/openrouter.py  ← OpenRouter (default)
adapters/llm/openai.py      ← OpenAI
adapters/llm/mock.py        ← Mock (tests + offline)
adapters/embedding/jina.py  ← Jina AI embeddings
adapters/embedding/mock.py  ← Zero-vector stub (tests)
```

Swapping providers = change `LLM_PROVIDER` in `.env`, restart app. Zero service layer changes.

```
LLM_PROVIDER=openrouter  → OpenRouterLLMAdapter
LLM_PROVIDER=openai      → OpenAILLMAdapter
LLM_PROVIDER=mock        → MockLLMAdapter
```

Dependency injection is handled at app startup in `adapters/factory.py` — services
receive adapters as constructor arguments, never instantiate them themselves.

---

## 6. Knowledge Base & pgvector Flow

### Indexing (runs automatically on container startup)
```
knowledge_base/*.txt
        │
        ▼
  chunk by paragraph (~300 chars each, split on \n\n)
  filter: len >= 20 chars
  hash: MD5(content) — skip if unchanged (idempotent)
        │
        ▼
  JinaEmbeddingAdapter.embed(chunk, task="retrieval.passage") → vector[1024]
        │
        ▼
  KnowledgeRepository.upsert(source_file, chunk_index, content, hash, vector)
        │
        ▼
  knowledge_chunks table  (PostgreSQL + pgvector, dim=1024)
```

Re-indexing: `python manage.py index_knowledge_base` — idempotent, safe to re-run.
Only changed or new chunks hit the Jina API.

### Query (on every message)
```
user_message
        │
        ▼
  JinaEmbeddingAdapter.embed(message, task="retrieval.query") → query_vector[1024]
        │
        ▼
  SELECT content, source_file, chunk_index,
         1 - (embedding <=> %s::vector) AS similarity
  FROM knowledge_chunks
  ORDER BY embedding <=> %s::vector
  LIMIT 4;
        │
        ▼
  top-4 RetrievedChunks + similarity scores → EvaluatorService → GeneratorService
```

The `<=>` operator is pgvector cosine distance. Similarity = `1 - distance`.

---

## 7. Project Directory Structure

```
rastad/
├── rastad/                  # Django project
│   ├── settings/
│   │   ├── base.py          # all env vars loaded here
│   │   ├── development.py
│   │   ├── test.py          # LLM_PROVIDER=mock, EMBEDDING_PROVIDER=mock
│   │   └── production.py
│   ├── urls.py
│   └── wsgi.py
│
├── apps/
│   ├── api/                 # DRF views, serializers, URL routing
│   │   ├── views.py         # thin — calls pipeline, returns response
│   │   ├── serializers.py
│   │   └── urls.py
│   ├── users/               # RastadUser model + migration
│   │   └── models.py
│   ├── messages/            # Message model (app label: rastad_messages)
│   │   └── models.py
│   └── knowledge/           # KnowledgeChunk model + management command
│       ├── models.py
│       └── management/commands/index_knowledge_base.py
│
├── core/
│   ├── ports.py             # LLMPort, EmbeddingPort protocols
│   ├── types.py             # ClassificationResult, RetrievedChunk, PipelineResult
│   └── exceptions.py        # LLMError, EmbeddingError, ClassificationError
│
├── services/
│   ├── pipeline.py          # MessagePipeline — orchestrator, timing, logging
│   ├── classifier.py        # ClassifierService + RuleBasedClassifier
│   ├── retriever.py         # RetrieverService
│   ├── generator.py         # GeneratorService
│   └── evaluator.py         # EvaluatorService
│
├── repositories/
│   ├── user_repository.py   # get_or_create, update_last_seen_and_segment, list_users
│   ├── message_repository.py
│   └── knowledge_repository.py  # upsert, similarity_search (raw SQL pgvector)
│
├── adapters/
│   ├── factory.py           # build_pipeline(), get_llm(), get_embedder()
│   ├── llm/
│   │   ├── openrouter.py    # OpenRouter — Qwen3-8b, thinking block stripping
│   │   ├── openai.py        # OpenAI — gpt-4o-mini etc.
│   │   └── mock.py          # keyword-based, no network
│   └── embedding/
│       ├── jina.py          # Jina AI — jina-embeddings-v3, dim 1024
│       └── mock.py          # zero-vector stub for tests
│
├── knowledge_base/          # *.txt source files (Persian, paragraph format)
├── tests/
│   └── test_api.py          # pytest endpoint tests (mock LLM + mock embedder)
│
├── docs/                    # This directory
├── Dockerfile               # BuildKit cache mount for pip
├── docker-compose.yml       # app + pgvector/pgvector:pg16
├── entrypoint.sh            # wait for DB → migrate → index KB → runserver
├── .env.example
├── requirements.txt
└── README.md
```

---

## 8. Design Patterns Used

| Pattern | Where | Why |
|---|---|---|
| **Repository** | `repositories/` | Isolate DB from business logic |
| **Adapter / Port** | `adapters/` + `core/ports.py` | External APIs behind interfaces — swap provider via `.env` |
| **Pipeline** | `services/pipeline.py` | Sequential steps with timing and structured logging |
| **Strategy** | `LLMAdapter` variants | Runtime-selectable behavior via `LLM_PROVIDER` env var |
| **Dependency Injection** | `adapters/factory.py` | Services receive adapters as constructor args |

---

## 9. Error Handling & Fallback Strategy

```
LLM classify fails (or JSON invalid after 2 retries)
    → RuleBasedClassifier runs (Persian keyword matching)
    → intent = best keyword match or "unknown"
    → needs_human_support = True
    → log WARNING FALLBACK

LLM generate fails
    → use best-matching chunk content as template reply
    → needs_human_support = True
    → log WARNING FALLBACK

Embedding fails (Jina API down)
    → skip retrieval, return []
    → EvaluatorService: max_similarity=0.0 < threshold → needs_human=True
    → log WARNING FALLBACK

No chunks above confidence threshold (0.45)
    → EvaluatorService forces needs_human_support = True
    → reply = Persian handoff template

DB write fails
    → log ERROR, still return reply to user
    → never fail the user-facing response for a storage error
```

Fallback chain principle: **degrade gracefully, always return something, always log.**

---

## 10. Logging Strategy

Python `logging` module, written to stdout — visible in `docker compose logs`.

### Log format
```
[{LEVEL}] {PREFIX} | {key=value ...}
```

### Per-request pipeline log lines
```
[INFO    ] REQUEST  | user_id=12345 message_len=42
[INFO    ] REQUEST  | new user created user_id=1 name=Ali
[INFO    ] CLASSIFY | intent=vip_question latency_ms=820
[INFO    ] RETRIEVE | chunks=4 latency_ms=290
[WARNING ] EVALUATE | needs_human_support=True confidence=LOW similarity=0.31
[INFO    ] GENERATE | latency_ms=930
[INFO    ] DONE     | llm_ms=1750 embedding_ms=290 other_ms=60 total_ms=2100

[WARNING ] FALLBACK | LLM classify failed — using rule-based classifier: ...
[WARNING ] FALLBACK | LLM generate failed — using template reply: ...
[WARNING ] FALLBACK | embedding failed — skipping retrieval: ...

[ERROR   ] LLM      | OpenRouter request failed: ConnectionTimeout
[ERROR   ] EMBED    | Jina request failed: 429 RateLimited
[ERROR   ] DB       | Failed to save message: IntegrityError
```

### Log levels
| Level | Used for |
|---|---|
| `INFO` | Normal flow — every step of the pipeline on success |
| `WARNING` | Degraded but handled — fallback triggered, low confidence |
| `ERROR` | External failure — LLM down, DB error, embedding error |
| `CRITICAL` | Startup failure — DB unreachable, KB indexing failed |

No message content is logged above `DEBUG` level — only metadata.

---

## 11. Interview Readiness

**"Why Django over FastAPI?"**
Familiar with Django ORM + migrations, DRF serializers give free validation,
built-in admin is useful for inspecting data. For an async-heavy production
service with thousands of concurrent users, FastAPI would be the better choice.

**"How do you swap mock → OpenAI or another provider?"**
Change `LLM_PROVIDER=openai` and `OPENAI_API_KEY=sk-...` in `.env`, restart.
The factory routes to `OpenAILLMAdapter`. Zero service layer changes.

**"If user count grows 10×?"**
Add gunicorn workers in Dockerfile, add DB connection pooling (pgBouncer),
cache embeddings of common queries in Redis, extract LLM call to Celery + Redis.

**"If LLM goes down?"**
`RuleBasedClassifier` handles classification, template reply from best chunk
handles generation, `needs_human_support=True` on all responses. System stays up.

**"How to connect to Telegram or Rastad CRM?"**
Telegram: add `apps/telegram/` webhook view — call `MessagePipeline.process()`, return reply.
CRM: add `CRMAdapter` in `adapters/crm/` — call after `MessageRepository.save()`.
The pipeline doesn't change at all.
