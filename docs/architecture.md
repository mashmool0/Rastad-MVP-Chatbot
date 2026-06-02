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
│  MessageRepository       │   │  LLMAdapter (Mock)            │
│  KnowledgeRepository     │   │  EmbeddingAdapter (OpenRouter)│
└──────┬──────────────────┘   └───────────────────────────────┘
       │
┌──────▼──────────────────┐
│   PostgreSQL + pgvector  │
│  users · messages        │
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
     — validate: user_id not empty, message not empty
     — raise 400 if invalid
          │
          ▼
 [2] MessagePipeline.process(user_id, name, message)
     │
     ├─[2a] UserRepository.get_or_create(user_id, name)
     │       → upsert User row, return User object
     │
     ├─[2b] ClassifierService.classify(message)
     │       → try: LLMAdapter.classify(message) → {intent, segment, needs_human}
     │       → fallback: RuleBasedClassifier.classify(message)
     │       → return ClassificationResult
     │
     ├─[2c] RetrieverService.retrieve(message, top_k=4)
     │       → EmbeddingAdapter.embed(message) → vector[1536]
     │       → KnowledgeRepository.similarity_search(vector, top_k=4)
     │       → return list[KnowledgeChunk] with similarity scores
     │
     ├─[2d] EvaluatorService.evaluate(chunks, classification)
     │       → check: max similarity score < CONFIDENCE_THRESHOLD (0.45)
     │       → check: intent == "support_request"
     │       → check: classification.needs_human from LLM
     │       → return final needs_human_support: bool
     │         (if KB confidence is too low → force needs_human_support=True)
     │
     ├─[2e] GeneratorService.generate(message, chunks, classification)
     │       → build prompt: system context + KB chunks + user message
     │       → LLMAdapter.generate(prompt) → reply string
     │       → fallback: template reply from best-matching chunk
     │
     └─[2f] MessageRepository.save(...)
             UserRepository.update_last_seen_and_segment(...)
             → return saved Message object
          │
          ▼
 Response: { reply, intent, user_segment, needs_human_support }
```

---

## 4. The Evaluator — Design Decision

The evaluator sits between retrieval and generation. It answers one question:
**"Is the system confident enough to answer this, or should a human handle it?"**

Three approaches considered:

### Option A — LLM-as-judge (not chosen for MVP)
After generating the reply, a second LLM call rates the reply quality (1–10)
and rewrites if below threshold.
- Pro: highest quality control
- Con: doubles LLM API calls and latency, costs more, complicates the pipeline
- Decision: **too heavy for MVP**, but easy to add as a post-generation step later

### Option B — Confidence from KB similarity (chosen)
Use the cosine similarity score already computed during retrieval.
If the highest similarity score across all retrieved chunks is below a threshold,
the system doesn't have relevant knowledge — a human should respond instead.

```
max(chunk.similarity for chunk in chunks) < CONFIDENCE_THRESHOLD
    → needs_human_support = True
    → reply = "I'm connecting you with our support team."
```

- Pro: zero extra API calls, uses data we already have, fast, explainable
- Con: similarity threshold needs tuning per use case
- Decision: **chosen** — fits MVP scope, strong story in interview

### Option C — Rule-based post-processor (partial)
Check reply for minimum length, language (Persian expected), forbidden phrases.
Used as a lightweight supplement to Option B, not a replacement.

### Combined approach in this MVP
```
EvaluatorService.evaluate(chunks, classification):
    if max_similarity < 0.45:          → needs_human_support = True
    if classification.intent == "support_request": → needs_human_support = True
    if classification.needs_human (from LLM):      → needs_human_support = True
    else:                              → needs_human_support = False
```

`CONFIDENCE_THRESHOLD = 0.45` is configurable via `.env`.

---

## 5. LLMService — The Swappable Abstraction

All LLM and embedding calls go through protocol interfaces.
No service layer code ever imports `openai`, `anthropic`, or `requests` directly.

```python
# core/ports.py  (interfaces — no implementation here)

class LLMPort(Protocol):
    def classify(self, message: str) -> ClassificationResult: ...
    def generate_reply(self, message: str, chunks: list[str], intent: str) -> str: ...

class EmbeddingPort(Protocol):
    def embed(self, text: str) -> list[float]: ...
```

```python
# adapters/llm/openrouter.py   ← real implementation
# adapters/llm/mock.py         ← mock implementation
# adapters/embedding/openrouter.py
```

Swapping from OpenRouter to Claude API = replace one adapter file, change one
`LLM_PROVIDER` env var. Zero changes to service layer.

```
LLM_PROVIDER=openrouter   → uses OpenRouterLLMAdapter
LLM_PROVIDER=mock         → uses MockLLMAdapter
```

Dependency injection is handled at app startup in `apps.py` — the service layer
receives adapters as constructor arguments, never instantiates them itself.

---

## 6. Knowledge Base & pgvector Flow

### Indexing (runs once at startup via Django management command)
```
knowledge_base/*.txt
        │
        ▼
  chunk by paragraph (~300 tokens each)
        │
        ▼
  EmbeddingAdapter.embed(chunk) → vector
        │
        ▼
  KnowledgeRepository.upsert(source_file, content, vector)
        │
        ▼
  knowledge_chunks table  (PostgreSQL + pgvector)
```

Re-indexing: run `python manage.py index_knowledge_base` — idempotent, safe to re-run.

### Query (on every message)
```
user_message
        │
        ▼
  EmbeddingAdapter.embed(message) → query_vector
        │
        ▼
  SELECT content, 1 - (embedding <=> query_vector) AS similarity
  FROM knowledge_chunks
  ORDER BY embedding <=> query_vector
  LIMIT 4;
        │
        ▼
  top-4 chunks + similarity scores → EvaluatorService → GeneratorService
```

The `<=>` operator is pgvector cosine distance. Similarity = `1 - distance`.

---

## 7. Project Directory Structure

```
rastad/
├── rastad/                  # Django project
│   ├── settings/
│   │   ├── base.py
│   │   ├── development.py
│   │   └── production.py
│   ├── urls.py
│   └── wsgi.py
│
├── apps/
│   ├── api/                 # DRF views, serializers, URL routing
│   │   ├── views.py
│   │   ├── serializers.py
│   │   └── urls.py
│   ├── users/               # RastadUser model + migration
│   │   ├── models.py
│   │   └── migrations/
│   ├── messages/            # Message model + migration
│   │   ├── models.py
│   │   └── migrations/
│   ├── knowledge/           # KnowledgeChunk model + management command
│   │   ├── models.py
│   │   ├── management/commands/index_knowledge_base.py
│   │   └── migrations/
│   ├── auth_app/            # Signup / login / logout views
│   │   ├── views.py         # signup_view, login_view, logout_view
│   │   ├── forms.py         # SignupForm (username, name, password x2)
│   │   └── urls.py
│   └── ui/                  # Main page (login required)
│       ├── views.py
│       └── templates/
│           ├── ui/index.html
│           ├── auth/login.html
│           └── auth/signup.html
│
├── core/
│   ├── ports.py             # Protocol interfaces (LLMPort, EmbeddingPort)
│   ├── types.py             # Dataclasses: ClassificationResult, RetrievedChunk
│   └── exceptions.py        # Domain exceptions
│
├── services/
│   ├── pipeline.py          # MessagePipeline — main orchestrator
│   ├── classifier.py        # ClassifierService + RuleBasedClassifier
│   ├── retriever.py         # RetrieverService
│   ├── generator.py         # GeneratorService
│   └── evaluator.py         # EvaluatorService
│
├── repositories/
│   ├── user_repository.py
│   ├── message_repository.py
│   └── knowledge_repository.py
│
├── adapters/
│   ├── llm/
│   │   ├── openrouter.py    # Real LLM adapter
│   │   └── mock.py          # Mock adapter (deterministic, for tests + offline)
│   └── embedding/
│       └── openrouter.py    # Embedding adapter
│
├── knowledge_base/
│   ├── rastad_services.txt
│   ├── vip_products.txt
│   ├── exchange_signup.txt
│   └── kol_program.txt
│
├── docs/                    # This directory
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── requirements.txt
├── manage.py
└── README.md
```

---

## 8. Design Patterns Used

| Pattern | Where | Why |
|---|---|---|
| **Repository** | `repositories/` | Isolate DB from business logic — easy to swap DB or test |
| **Adapter / Port** | `adapters/` + `core/ports.py` | External APIs behind interfaces — swap LLM provider without touching service code |
| **Pipeline** | `services/pipeline.py` | Sequential steps with clear in/out — easy to add/remove a step |
| **Strategy** | `LLMAdapter` variants | Runtime-selectable behavior via `LLM_PROVIDER` env var |
| **Dependency Injection** | `apps.py` startup | Services receive dependencies — no hidden globals or `import` coupling |

---

## 9. Error Handling & Fallback Strategy

```
LLM classify fails
    → RuleBasedClassifier runs
    → intent = best keyword match or "unknown"
    → needs_human_support = True (we're uncertain)

LLM generate fails
    → use best-matching chunk content as template reply
    → needs_human_support = True

Embedding fails
    → skip retrieval, generate from intent alone
    → needs_human_support = True

No chunks above threshold
    → EvaluatorService forces needs_human_support = True
    → reply = "I'm connecting you with our support team."

DB write fails
    → log error, still return reply to user
    → do not fail the user-facing response for a storage error
```

Fallback chain principle: **degrade gracefully, always return something, always log.**

---

## 10. Logging Strategy

Python `logging` module, written to stdout — visible in `docker logs` and
captured in the UI JSON panel for the demo.

### Docker log format (human-readable lines)
Each event logs a prefixed line so Docker logs are scannable at a glance:

```
[INFO]    BOOT     | Knowledge base indexed — 24 chunks loaded
[INFO]    REQUEST  | user_id=12345 message_len=42
[INFO]    CLASSIFY | intent=vip_question segment=vip_interest
[INFO]    RETRIEVE | top_similarity=0.82 chunks=4
[INFO]    EVALUATE | needs_human_support=False confidence=HIGH
[INFO]    GENERATE | llm_provider=openrouter latency_ms=1240
[INFO]    DONE     | user_id=12345 total_ms=1380

[WARNING] EVALUATE | needs_human_support=True confidence=LOW similarity=0.31
[WARNING] FALLBACK | LLM classify failed — using rule-based classifier
[WARNING] FALLBACK | LLM generate failed — using template reply

[ERROR]   LLM      | OpenRouter request failed: ConnectionTimeout
[ERROR]   EMBED    | Embedding request failed: 429 RateLimited
[ERROR]   DB       | Failed to save message: IntegrityError
```

### Log levels
| Level | Used for |
|---|---|
| `INFO` | Normal flow — every step of the pipeline on success |
| `WARNING` | Degraded but handled — fallback triggered, low confidence |
| `ERROR` | External failure — LLM down, DB error, embedding error |
| `CRITICAL` | Startup failure — DB unreachable, KB indexing failed |

### Structured payload (also sent to UI JSON panel)
After each request the pipeline emits one structured dict captured by the UI:

```json
{
  "timestamp": "2026-06-02T14:23:01Z",
  "user_id": "12345",
  "intent": "vip_question",
  "segment": "vip_interest",
  "needs_human_support": false,
  "confidence": "HIGH",
  "top_chunk_similarity": 0.82,
  "chunks_used": ["vip_products.txt:§2", "rastad_services.txt:§1"],
  "llm_provider": "openrouter",
  "fallback_used": false,
  "latency_ms": 1380,
  "error": null
}
```

No message content is logged above `DEBUG` level — only metadata.

---

## 11. Interview Readiness

Prepared answers for their likely questions:

**"Why Django over FastAPI?"**
Familiar with Django ORM + migrations, DRF serializers give free validation,
built-in admin is useful for inspecting data. For an async-heavy production
service with thousands of concurrent users, FastAPI would be the better choice —
acknowledged as a known trade-off.

**"How do you swap mock → Claude API?"**
Create `adapters/llm/claude.py` implementing `LLMPort`, change `LLM_PROVIDER=claude`
in `.env`. Zero changes to service layer.

**"If user count grows 10×?"**
Add `gunicorn` workers in Dockerfile, add DB connection pooling (pgBouncer or
`django-db-geventpool`), cache embeddings of common queries in Redis,
and consider extracting the LLM call to an async task queue (Celery + Redis).

**"If LLM goes down?"**
`RuleBasedClassifier` handles classification, template reply from best chunk
handles generation, `needs_human_support=True` on all responses.
System stays up and responds — just without LLM quality.

**"How to connect to Telegram or Rastad CRM?"**
Telegram: add a `apps/telegram/` app with a webhook view — it receives updates,
calls `MessagePipeline.process()`, and sends the reply back via Telegram Bot API.
The pipeline doesn't change at all.
CRM: add a `CRMAdapter` in `adapters/crm/` — call it at the end of the pipeline
after `MessageRepository.save()` to push lead data. Again, pipeline orchestrates,
adapter handles the integration.
