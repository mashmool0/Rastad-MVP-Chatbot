# Rastad AI Lead & Support Assistant — Backend + Pipeline Build Plan

## Context

The repo currently holds only `docs/` (a complete, high-quality spec) and 4 Persian
`knowledge_base/*.txt` files. No Django code exists yet. The goal of **this pass** is to
build the full backend and AI pipeline end-to-end so that `POST /api/message` works against
a real LLM, with semantic KB retrieval, classification, evaluation, generation, persistence,
structured logging, and tests. The single-page UI, login/signup pages, and the app Docker
image are intentionally **deferred to a second pass** (only a DB container is needed now).

### Decisions locked with the user
- **Embeddings:** Jina AI `jina-embeddings-v3`, **dimension 1024**, via `JINA_API_KEY`
  (separate free key). `VectorField(dimensions=1024)` — overrides the doc's `1536`.
- **LLM:** Real OpenRouter `qwen/qwen3-8b` from the start. Mock adapter still built (tests).
- **Scope:** Backend + pipeline. No `apps/auth_app`, no `apps/ui` this pass.
- **Env naming:** Keep the existing `LLM_API_KEY` (already in `.env`, an `sk-or-v1-…` key)
  as the OpenRouter key; add `JINA_API_KEY`. Reconcile docs that say `OPENROUTER_API_KEY`.

### One design tension to resolve in code (default chosen)
The API is open and takes `user_id`, but `RastadUser.auth_user` is a non-null `OneToOneField`
in the data-model doc. To let the open API create users without a signup/auth account:
make **`auth_user` nullable** (`null=True, blank=True`). `UserRepository.get_or_create`
looks up by `user_id`; if absent, it creates a `RastadUser` (DB assigns `user_id`,
`auth_user=None`) and returns it. Signup (2nd pass) links an `auth.User` later.

---

## Build Steps (in order)

### Step 1 — Project skeleton & config
- `requirements.txt`: `Django`, `djangorestframework`, `psycopg[binary]`, `pgvector`,
  `pydantic`, `requests`, `python-dotenv`, `pytest`, `pytest-django`.
- `manage.py`; Django project package `rastad/` with split settings:
  `settings/base.py`, `development.py`, `production.py`, plus `urls.py`, `wsgi.py`, `asgi.py`.
- `base.py`: load `.env` via `python-dotenv`; `DATABASES` → Postgres from env
  (`DB_NAME/USER/PASSWORD/HOST/PORT`); read `LLM_PROVIDER`, `LLM_API_KEY`, `LLM_MODEL`,
  `JINA_API_KEY`, `EMBEDDING_MODEL`, `EMBEDDING_DIM=1024`, `CONFIDENCE_THRESHOLD=0.45`,
  `RETRIEVE_TOP_K=4`; `INSTALLED_APPS` += DRF + the apps below; `LOGGING` config (Step 9).
- `.env.example` (all keys, no secrets). Keep real `.env` untouched/gitignored.

### Step 2 — Core domain (`core/`)
- `core/types.py`: pydantic `ClassificationResult` (the two `Literal` enums +
  `needs_human_support: bool`); dataclass `RetrievedChunk(content, source_file, chunk_index, similarity)`;
  `PipelineResult` dataclass for the structured response/log payload.
- `core/ports.py`: `LLMPort` and `EmbeddingPort` `Protocol`s (per `docs/llm-and-kb.md §2`).
- `core/exceptions.py`: `LLMError`, `EmbeddingError`, `ClassificationError`.

### Step 3 — Models & migrations
- `apps/users/models.py`: `RastadUser` (per data-model doc) — **`auth_user` nullable**,
  `SEGMENT_CHOICES`, `db_table="rastad_users"`.
- `apps/messages/models.py`: `Message` (FK→RastadUser, `INTENT_CHOICES`, `db_table="messages"`,
  ordering + user index).
- `apps/knowledge/models.py`: `KnowledgeChunk` with `from pgvector.django import VectorField`,
  `embedding = VectorField(dimensions=1024)`, `unique_together(source_file, chunk_index)`.
- Migrations: `knowledge/0001_enable_pgvector` (`RunSQL CREATE EXTENSION vector`),
  `0002` `CreateModel` (depends on 0001), `0003` ivfflat index via `RunSQL`
  (`vector_cosine_ops`, `lists=10`) — per `docs/data-model.md §5`. `makemigrations` for users/messages.

### Step 4 — Repositories (`repositories/`)
- `user_repository.py`: `get_or_create(user_id, name)`, `update_last_seen_and_segment(...)`.
- `message_repository.py`: `save(user, user_message, reply, intent, needs_human)`,
  `list_for_user(user_id)`, `list_users()`.
- `knowledge_repository.py`: `upsert(source_file, chunk_index, content, content_hash, embedding)`,
  `get_existing(source_file, chunk_index)`, and `similarity_search(vector, top_k)` using
  pgvector cosine (`1 - (embedding <=> %s)`), returning `RetrievedChunk`s.

### Step 5 — Adapters (`adapters/`)
- `llm/openrouter.py` — implements `LLMPort`. POST `https://openrouter.ai/api/v1/chat/completions`,
  `Bearer LLM_API_KEY`, model `LLM_MODEL` (`qwen/qwen3-8b`). `classify()`: send the Persian
  classification prompt (`docs/llm-and-kb.md §4`), `json.loads` → `ClassificationResult`,
  **pydantic-validated retry loop (max 2)** with the Persian error-injection prompt (§3);
  raise `LLMError` after exhausting retries. `generate_reply()`: grounded Persian prompt (§5).
- `llm/mock.py` — deterministic keyword map (`docs/llm-and-kb.md §6`). Used by tests.
- `embedding/jina.py` — implements `EmbeddingPort`. POST `https://api.jina.ai/v1/embeddings`,
  `Bearer JINA_API_KEY`, `{model: "jina-embeddings-v3", input:[text], task: "retrieval.query"}`
  (indexer uses `retrieval.passage`); returns `list[float]` len 1024; raise `EmbeddingError`.
- DI factory `adapters/factory.py`: `get_llm()` returns OpenRouter or Mock by `LLM_PROVIDER`;
  `get_embedder()` returns Jina. Wired so services receive adapters as constructor args.

### Step 6 — Services (`services/`)
- `classifier.py`: `ClassifierService(llm)` tries `llm.classify`; on `LLMError`/validation
  exhaustion → `RuleBasedClassifier` (Persian keyword map) with `needs_human_support=True`,
  logs `WARNING FALLBACK`.
- `retriever.py`: `RetrieverService(embedder, knowledge_repo)` → embed message →
  `similarity_search(top_k)`. On `EmbeddingError`: return `[]`, log fallback.
- `evaluator.py`: `EvaluatorService` — `needs_human` if `max(similarity) < CONFIDENCE_THRESHOLD`
  OR `intent == "support_request"` OR `llm.needs_human` (three-signal, `docs/architecture.md §4`).
- `generator.py`: `GeneratorService(llm)` → grounded reply; if no chunks above threshold →
  the Persian handoff template; on `LLMError` → template from best chunk, fallback flagged.
- `pipeline.py`: `MessagePipeline.process(user_id, name, message)` orchestrates 2a–2f from
  `docs/architecture.md §3`, builds the structured payload, persists via repos. DB write wrapped
  so a storage error logs but still returns the reply.

### Step 7 — KB indexing command
- `apps/knowledge/management/commands/index_knowledge_base.py`: read `knowledge_base/*.txt`,
  split on `\n\n`, drop chunks `< 20` chars, md5 `content_hash`, **idempotent** skip when
  hash unchanged, else `embed(content, task=passage)` → `knowledge_repo.upsert`. Logs
  `[INFO] BOOT | … chunks loaded` (`docs/architecture.md §6`, `docs/llm-and-kb.md §8`).

### Step 8 — API layer (`apps/api/`)
- `serializers.py`: `MessageRequestSerializer` (`user_id`, `name` optional, `message` non-empty);
  response serializers for message + admin lists.
- `views.py` (DRF, no business logic): `POST /api/message` → `MessagePipeline.process` →
  `{reply, intent, user_segment, needs_human_support}` (+ inspector fields for the future UI);
  `GET /api/users`; `GET /api/users/{user_id}/messages`.
- `apps/api/urls.py` + include in `rastad/urls.py`.

### Step 9 — Logging
- `logging` config in settings → stdout. Human-readable prefixed lines
  (`[INFO] CLASSIFY | …`, etc., `docs/architecture.md §10`) and the structured per-request
  dict. No message content above DEBUG.

### Step 10 — Tests & local DB
- `conftest.py` / `pytest.ini` (`pytest-django`, `DJANGO_SETTINGS_MODULE=rastad.settings.development`).
- Endpoint tests on `POST /api/message` running with `LLM_PROVIDER=mock` and a stubbed embedder:
  valid message → 200 + expected intent/segment; empty message → 400;
  `support_request` keyword → `needs_human_support=True`.
- Local DB for dev/verify: run the official pgvector image standalone
  (`docker run -e POSTGRES_… -p 5432:5432 pgvector/pgvector:pg16`) — full `docker-compose`/app
  `Dockerfile` are the 2nd pass.

---

## Critical files to create
- `rastad/settings/base.py`, `rastad/urls.py`, `manage.py`
- `core/types.py`, `core/ports.py`
- `apps/users/models.py`, `apps/messages/models.py`, `apps/knowledge/models.py`
- `apps/knowledge/migrations/0001_enable_pgvector.py`, `…/0003_add_vector_index.py`
- `repositories/knowledge_repository.py`, `repositories/user_repository.py`
- `adapters/llm/openrouter.py`, `adapters/llm/mock.py`, `adapters/embedding/jina.py`, `adapters/factory.py`
- `services/pipeline.py`, `services/classifier.py`, `services/retriever.py`, `services/evaluator.py`, `services/generator.py`
- `apps/api/views.py`, `apps/api/serializers.py`, `apps/api/urls.py`
- `apps/knowledge/management/commands/index_knowledge_base.py`
- `requirements.txt`, `.env.example`, `pytest.ini`

## Reused / existing assets
- `knowledge_base/*.txt` (already authored, correct `\n\n` paragraph format).
- `.env` already has the OpenRouter key as `LLM_API_KEY`.
- All prompts, enums, thresholds, and SQL are specified verbatim in `docs/llm-and-kb.md`,
  `docs/architecture.md`, and `docs/data-model.md` — implement to those.

---

## Verification (end-to-end)
1. Start pgvector Postgres (`docker run … pgvector/pgvector:pg16`); set `.env` DB vars + `JINA_API_KEY`.
2. `python manage.py migrate` — confirm extension + ivfflat index created.
3. `python manage.py index_knowledge_base` — confirm `BOOT | N chunks loaded`, rows in
   `knowledge_chunks` with non-null 1024-dim embeddings; re-run → idempotent (no re-embeds).
4. `python manage.py runserver`, then real call:
   `curl -X POST localhost:8000/api/message -H 'Content-Type: application/json'
   -d '{"user_id":"1","name":"Ali","message":"خدمات VIP راستاد چیه؟"}'`
   → expect Persian grounded reply, `intent=vip_question`, `needs_human_support=false`.
5. Support case: message with `مشکل پرداخت` → `needs_human_support=true`.
6. Admin: `GET /api/users` and `GET /api/users/1/messages` return persisted data.
7. `pytest` — endpoint tests pass on mock (no network).
8. Inspect Docker/stdout logs for the prefixed pipeline lines.
