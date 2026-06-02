# MVP Scope — Rastad AI Lead & Support Assistant

## 1. Project Goal

Rastad users send messages through a chat interface asking about VIP services,
exchange registration, KOL collaboration, payment issues, or general support.
This system receives those messages, classifies the intent and user segment,
retrieves relevant answers from Rastad's internal knowledge base using semantic
search, generates a grounded reply through an LLM, and stores the full
interaction in a database. The result is a small but real AI-driven support
assistant that can be demoed, inspected, and extended.

---

## 2. In-Scope Features (Mandatory)

### 2.1 Backend — Django + DRF
- Framework: Python / Django with Django REST Framework
- All business logic lives in a layered monolith: API → Services → Repositories → Adapters
- DRF serializers handle input validation (no raw request.data access in views)

### 2.2 Main Endpoint
```
POST /api/message
```
Input:
```json
{ "user_id": "12345", "name": "Ali", "message": "خدمات VIP راستاد چیه؟" }
```
Output:
```json
{
  "reply": "...",
  "intent": "vip_question",
  "user_segment": "vip_interest",
  "needs_human_support": false
}
```

### 2.3 Admin Endpoints
```
GET /api/users
GET /api/users/{user_id}/messages
```

### 2.4 Database — PostgreSQL + pgvector
- PostgreSQL as the primary database
- pgvector extension for semantic similarity search inside the same DB (no second vector store)
- Django ORM + migrations for all schema changes

**Models:**

| Model | Fields |
|---|---|
| User | user_id (PK), name, segment, created_at, last_seen_at |
| Message | id, user_id (FK), user_message, assistant_reply, intent, needs_human_support, created_at |
| KnowledgeChunk | id, source_file, content, embedding (vector) |

### 2.5 Intent & Segment Classification
- **Primary**: OpenRouter LLM call with a structured prompt that returns JSON
- **Fallback**: rule-based keyword classifier (runs when LLM fails or is unavailable)
- Classification always produces one intent and one segment from the fixed enums below

**Segments:** `new_user` · `vip_interest` · `exchange_signup` · `kol_candidate` · `support_needed` · `general_question`

**Intents:** `vip_question` · `exchange_registration` · `kol_collaboration` · `support_request` · `general_info` · `unknown`

### 2.6 Knowledge Base
- Directory: `knowledge_base/`
- Files (minimum 4):
  - `rastad_services.txt`
  - `vip_products.txt`
  - `exchange_signup.txt`
  - `kol_program.txt`
- Files are chunked and embedded at startup into PostgreSQL (via pgvector)
- At query time: user message is embedded → top-K chunks retrieved by cosine similarity → chunks injected into LLM prompt as context
- Reply must be grounded in retrieved chunks, not generic LLM output

### 2.7 Embeddings Provider
- **OpenRouter** — same provider, same API key as the LLM
- One account, one key, one place — no second provider to manage
- Embedding model to be confirmed during implementation (free tier on OpenRouter)
- Configured via `OPENROUTER_API_KEY` in `.env`

### 2.8 LLM — OpenRouter (Real)
- Provider: OpenRouter (free-tier model, e.g. `mistralai/mistral-7b-instruct`)
- Used for: intent/segment classification + reply generation
- Accessed through a single `LLMService` interface — swapping to Claude or OpenAI requires changing only the adapter, not the rest of the code
- `LLM_PROVIDER=mock` in `.env` activates a clean mock that bypasses all API calls

### 2.9 Error Handling & Logging
- Handles: empty message, empty user_id, unknown user, LLM timeout/error, no KB match
- Python structured logging (JSON format) on every request: user_id, timestamp, intent, segment, latency, errors
- Logs visible in Docker stdout and in the UI JSON panel (last request only)

### 2.10 UI (Single Page)
- One HTML + CSS page served by Django
- **Left panel**: user input (user_id, name, message) + submit button + reply display
- **Right panel**: live JSON showing intent, segment, needs_human_support, top KB chunks used, log of last request
- Purpose: demo visibility — evaluators see everything without reading logs in terminal

### 2.11 Docker
- `Dockerfile` for the Django app
- `docker-compose.yml` running: app + PostgreSQL (with pgvector) — two services, one command
- `.env.example` with all required keys, no real values committed

### 2.12 README
Full README covering: project description, tech stack, install & run locally, Docker/Compose run, architecture summary, LLM mode (real vs mock), sample requests/responses, limitations.

---

## 3. Chosen Bonus Features

| Bonus | Reason |
|---|---|
| pgvector | Semantic KB search, keeps everything in one DB |
| Docker Compose | Low effort, high signal — one command to run the full stack |
| Endpoint tests (pytest) | 2–3 tests on `POST /message`, directly scored |
| Smarter `needs_human_support` | Rule: `support_request` intent OR low KB similarity score → `true` |

---

## 4. Explicitly Out of Scope

Per the task brief — not built, not partially built:

- UI admin panel or dashboard beyond the single demo page
- Full authentication / authorization system
- Real Rastad CRM or exchange integration
- Payment processing
- Telegram Bot
- LangGraph or multi-agent orchestration
- Redis / queue / async workers
- Rate limiting
- Kubernetes / CI/CD
- Production deployment (Docker only, run locally)

---

## 5. Score Mapping

| Rubric Criterion | Points | Our Coverage |
|---|---|---|
| Runs correctly | 20 | Docker Compose, endpoint tests, live demo |
| Backend & code quality | 20 | DRF serializers, layered architecture, no business logic in views |
| AI logic & classification | 20 | OpenRouter LLM + rule-based fallback, structured `LLMService` |
| Knowledge base usage | 15 | pgvector semantic search, KB chunks injected into every prompt |
| Production-readiness | 15 | Docker, structured JSON logging, env-based config, LLM fallback |
| Documentation | 10 | README + this `docs/` directory |
| **Total** | **100** | |

Bonus points targeted: pgvector (+), Docker Compose (+), tests (+), smarter `needs_human_support` (+).

---

## 6. Known Limitations

These are intentional trade-offs for a 2-day MVP, stated honestly:

- **Knowledge base is placeholder**: fictional Rastad content — real data not available
- **No authentication**: endpoints are open; any caller can query any user's history
- **Single instance only**: no horizontal scaling, no connection pooling beyond Django defaults
- **Embedding index is static**: KB is embedded once at startup; adding new files requires restart
- **No streaming replies**: LLM response is returned as a complete string, not streamed
- **HuggingFace free tier**: rate-limited; not suitable for production traffic
- **SQLite not used**: PostgreSQL requires Docker or a local PG install (no zero-config run option)

*Given more time: add auth, streaming, a management command to re-embed KB incrementally, and swap HF free tier for a hosted embedding service.*
