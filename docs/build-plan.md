# Rastad AI Lead & Support Assistant — Build Plan

> **Status: Backend + pipeline complete.** All 10 steps done.
> Deferred to 2nd pass: single-page UI, login/signup pages.

---

## Decisions locked during build

| Decision | Spec said | Actual |
|---|---|---|
| Embeddings provider | OpenRouter (no endpoint) | Jina AI `jina-embeddings-v3` |
| Embedding dimension | 1536 | **1024** (matches Jina model) |
| `auth_user` field | non-null OneToOne | **nullable** — open API creates users without auth |
| OpenRouter env key | `OPENROUTER_API_KEY` | **`LLM_API_KEY`** (already present in .env) |
| `list_users` location | MessageRepository | **UserRepository** (correct ownership) |
| messages app label | `messages` | **`rastad_messages`** (conflict with Django built-in) |
| DB host port | 5432 | **5433** (avoid clash with local Postgres) |
| LLM providers | openrouter + mock | **openrouter + openai + mock** |

---

## Step 1 — Project skeleton & config ✓

- `requirements.txt`, `manage.py`
- `rastad/settings/base.py` — loads `.env`, all config vars
- `rastad/settings/development.py`, `test.py`, `production.py`
- `rastad/urls.py`, `wsgi.py`, `asgi.py`
- Minimal app skeletons (`apps/users`, `apps/messages`, `apps/knowledge`, `apps/api`)
- `.env.example`
- `.venv/` virtual environment

---

## Step 2 — Core domain ✓

- `core/types.py` — `ClassificationResult` (pydantic), `RetrievedChunk`, `PipelineResult`
  - `PipelineResult` includes `llm_ms`, `embedding_ms`, `other_ms` timing fields
- `core/ports.py` — `LLMPort`, `EmbeddingPort` protocols
  - `EmbeddingPort.embed()` takes `task` param for Jina passage/query distinction
- `core/exceptions.py` — `LLMError`, `EmbeddingError`, `ClassificationError`

---

## Step 3 — Models & migrations ✓

- `apps/users/models.py` — `RastadUser` with nullable `auth_user`
- `apps/messages/models.py` — `Message`, label `rastad_messages`
- `apps/knowledge/models.py` — `KnowledgeChunk`, `VectorField(dimensions=1024)`
- `apps/knowledge/migrations/0001_enable_pgvector.py` — `CREATE EXTENSION vector`
- `apps/knowledge/migrations/0002_initial.py` — auto-generated `CreateModel`
- `apps/knowledge/migrations/0003_add_vector_index.py` — `ivfflat` (lists=10)
- `apps/users/migrations/0001_initial.py` — auto-generated
- `apps/messages/migrations/0001_initial.py` — auto-generated

---

## Step 4 — Repositories ✓

- `repositories/user_repository.py` — `get_or_create`, `update_last_seen_and_segment`, `list_users`
- `repositories/message_repository.py` — `save`, `list_for_user`
- `repositories/knowledge_repository.py` — `upsert`, `get_existing`, `similarity_search` (raw SQL pgvector)

---

## Step 5 — Adapters ✓

- `adapters/llm/openrouter.py` — OpenRouter, `_strip_thinking()`, pydantic retry loop, `temperature=0.3`
- `adapters/llm/openai.py` — OpenAI chat completions, same interface
- `adapters/llm/mock.py` — keyword map
- `adapters/embedding/jina.py` — Jina AI, `task` param (`retrieval.passage` / `retrieval.query`)
- `adapters/embedding/mock.py` — zero-vector stub, dim from `settings.EMBEDDING_DIM`
- `adapters/factory.py` — `get_llm()`, `get_embedder()`, `build_pipeline()`
  - Routes `openrouter | openai | mock` via `LLM_PROVIDER`
  - Routes `jina | mock` via `EMBEDDING_PROVIDER`

---

## Step 6 — Services ✓

- `services/classifier.py` — `ClassifierService` + `RuleBasedClassifier` (8 Persian/English keywords)
- `services/retriever.py` — embed → similarity search → return `RetrievedChunk` list
- `services/evaluator.py` — three-signal `needs_human` logic
- `services/generator.py` — LLM generate with handoff template fallback
- `services/pipeline.py` — full orchestrator with per-step timing:
  - `llm_ms` = classify + generate
  - `embedding_ms` = Jina + pgvector
  - `other_ms` = user lookup + evaluation + DB write

---

## Step 7 — KB indexing command ✓

- `apps/knowledge/management/commands/index_knowledge_base.py`
- Paragraph split (`\n\n`), min 20 chars, MD5 hash, idempotent skip
- Embeds with `task="retrieval.passage"`
- Logs `BOOT | N new, M unchanged, T total chunks`
- Runs automatically in `entrypoint.sh` on container start

---

## Step 8 — API layer ✓

- `apps/api/serializers.py` — `MessageRequestSerializer`, `UserSerializer`, `MessageSerializer`
- `apps/api/views.py` — three `@api_view` functions, pipeline wired once at import time
- `apps/api/urls.py` — `POST /api/message`, `GET /api/users`, `GET /api/users/<id>/messages`
- Response includes `latency: { total_ms, llm_ms, embedding_ms, other_ms }`

---

## Step 9 — Logging ✓

- Configured in `rastad/settings/base.py`
- Format: `[LEVEL] PREFIX | key=value`
- Per-step prefixes: `REQUEST`, `CLASSIFY`, `RETRIEVE`, `EVALUATE`, `GENERATE`, `DONE`, `FALLBACK`
- Timing logged on each step and in `DONE` summary line
- No message content above DEBUG

---

## Step 10 — Docker + Tests ✓

- `Dockerfile` — BuildKit pip cache mount (no `--no-cache-dir`)
- `docker-compose.yml` — app + `pgvector/pgvector:pg16`, DB on host port 5433
- `entrypoint.sh` — Python socket wait → `migrate` → `index_knowledge_base` → `runserver`
- `pytest.ini` — `DJANGO_SETTINGS_MODULE=rastad.settings.test`
- `tests/test_api.py` — 6 endpoint tests, mock LLM + mock embedder, no network

---

## 2nd Pass (deferred)

- `apps/auth_app/` — signup / login / logout views + forms
- `apps/ui/` — single-page HTML + Tailwind + vanilla JS chat UI
- App `Dockerfile` production mode — gunicorn instead of `runserver`
- Full `docker-compose.yml` with `AUTH_*` env vars
