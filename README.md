# Rastad AI Lead & Support Assistant

An AI-powered support chatbot for the Rastad crypto platform. Classifies user intent, retrieves relevant answers from a knowledge base using semantic search (pgvector), and generates grounded Persian replies via an LLM.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.12 · Django 4.2 · Django REST Framework |
| Database | PostgreSQL 16 + pgvector (semantic search) |
| LLM | OpenRouter — `qwen/qwen3-8b` |
| Embeddings | HuggingFace — `intfloat/multilingual-e5-base` (dim 768) |
| Container | Docker · Docker Compose |

---

## Requirements

**Only Docker is required.** Nothing else needs to be installed on your system.

- [Docker](https://docs.docker.com/get-docker/) (includes Docker Compose)

---

## Setup & Run

### 1 — Clone the repository

```bash
git clone https://github.com/mashmool0/Rastad-MVP-Chatbot.git
cd Rastad-MVP-Chatbot
```

### 2 — Configure environment

Copy the example env file and fill in your API keys:

```bash
cp .env.example .env
```

Open `.env` and set:

```env
LLM_API_KEY=sk-or-v1-...                 # OpenRouter API key  → openrouter.ai
HUGGINGFACE_API_KEY=hf_...               # HuggingFace token   → huggingface.co/settings/tokens (free)
```

Everything else has working defaults and does not need to change.

### 3 — Start

```bash
docker compose up -d --build
```

That's it. On first run, Docker will:

1. Pull the `pgvector/pgvector:pg16` image (PostgreSQL + pgvector pre-installed)
2. Build the Django app image
3. Wait for the database to be ready
4. Run all migrations automatically
5. Embed all knowledge base files into pgvector via HuggingFace
6. Start the API server on `http://localhost:8000`

### Watch the boot logs

```bash
docker compose logs -f app
```

You should see:

```
[BOOT] Waiting for PostgreSQL at db:5432...
[BOOT] PostgreSQL is up.
[BOOT] Running migrations...
[BOOT] Indexing knowledge base...
[INFO] BOOT | Knowledge base indexed — 23 new, 0 unchanged, 23 total chunks
[BOOT] Starting server...
Starting development server at http://0.0.0.0:8000/
```

### Stop

```bash
docker compose down
```

---

## API Endpoints

| Method | URL | Description |
|---|---|---|
| `POST` | `/api/message` | Send a message, get an AI reply |
| `GET` | `/api/users` | List all users |
| `GET` | `/api/users/{id}/messages` | Message history for a user |

### Request format — `POST /api/message`

```json
{
  "user_id": 1,
  "name": "Ali",
  "message": "خدمات VIP راستاد چیه؟"
}
```

- `user_id` — optional integer. Omit to auto-create a new user.
- `name` — optional string. Defaults to `کاربر`.
- `message` — required, non-empty.

### Response format

```json
{
  "reply": "اشتراک VIP راستاد دسترسی به سیگنال‌های اختصاصی...",
  "intent": "vip_question",
  "user_segment": "vip_interest",
  "needs_human_support": false,
  "confidence": 0.8766,
  "chunks_used": ["vip_products.txt §1", "rastad_services.txt §2"],
  "llm_provider": "openrouter",
  "fallback_used": false,
  "latency": {
    "total_ms": 2045,
    "llm_ms": 1750,
    "embedding_ms": 290,
    "other_ms": 5
  }
}
```

The `latency` object is split into three buckets — `llm_ms` (both LLM calls),
`embedding_ms` (HuggingFace embed + pgvector search), and `other_ms` (DB + logic) —
so you can see exactly where each request spends its time.

---

## Testing with curl

Install `jq` for readable JSON output:

```bash
sudo apt-get install -y jq       # Debian / Ubuntu
brew install jq                  # macOS
```

---

### POST /api/message

**VIP question**
```bash
curl -s -X POST http://localhost:8000/api/message \
  -H "Content-Type: application/json" \
  -d '{"name": "Ali", "message": "خدمات VIP راستاد چیه؟"}' | jq
```
Example response:
```json
{
  "reply": "اشتراک VIP راستاد دسترسی به سیگنال‌های اسپات و فیوچرز، تحلیل‌های تکنیکال و پشتیبانی ویژه را فراهم می‌کند.",
  "intent": "vip_question",
  "user_segment": "vip_interest",
  "needs_human_support": false,
  "confidence": 0.8766,
  "chunks_used": ["vip_products.txt §1", "rastad_services.txt §2", "vip_products.txt §2", "kol_program.txt §2"],
  "llm_provider": "openrouter",
  "fallback_used": false,
  "latency": { "total_ms": 2045, "llm_ms": 1750, "embedding_ms": 290, "other_ms": 5 }
}
```

**Exchange registration**
```bash
curl -s -X POST http://localhost:8000/api/message \
  -H "Content-Type: application/json" \
  -d '{"name": "Sara", "message": "چطور در صرافی ثبت نام کنم؟"}' | jq
```
Example response:
```json
{
  "reply": "برای ثبت‌نام در صرافی معرفی‌شده راستاد، از طریق لینک اختصاصی ثبت‌نام کرده و مراحل احراز هویت (KYC) را کامل کنید.",
  "intent": "exchange_registration",
  "user_segment": "exchange_signup",
  "needs_human_support": false,
  "confidence": 0.7913,
  "chunks_used": ["exchange_signup.txt §0", "exchange_signup.txt §2", "rastad_services.txt §1", "vip_products.txt §0"],
  "llm_provider": "openrouter",
  "fallback_used": false,
  "latency": { "total_ms": 1980, "llm_ms": 1700, "embedding_ms": 275, "other_ms": 5 }
}
```

**KOL collaboration**
```bash
curl -s -X POST http://localhost:8000/api/message \
  -H "Content-Type: application/json" \
  -d '{"name": "Reza", "message": "میخوام با راستاد همکاری KOL داشته باشم"}' | jq
```
Example response:
```json
{
  "reply": "برنامه KOL راستاد برای همکاری اینفلوئنسرها و تحلیلگران است؛ پس از ثبت درخواست، تیم راستاد شرایط و مزایای همکاری را بررسی می‌کند.",
  "intent": "kol_collaboration",
  "user_segment": "kol_candidate",
  "needs_human_support": false,
  "confidence": 0.8102,
  "chunks_used": ["kol_program.txt §0", "kol_program.txt §2", "rastad_services.txt §0", "vip_products.txt §1"],
  "llm_provider": "openrouter",
  "fallback_used": false,
  "latency": { "total_ms": 2100, "llm_ms": 1820, "embedding_ms": 275, "other_ms": 5 }
}
```

**Support request — expect `needs_human_support: true`**
```bash
curl -s -X POST http://localhost:8000/api/message \
  -H "Content-Type: application/json" \
  -d '{"name": "Maryam", "message": "مشکل پرداخت دارم، اشتراکم فعال نشده"}' | jq
```
Example response — note `needs_human_support: true` is forced by the
`support_request` intent even though the KB confidence is acceptable:
```json
{
  "reply": "برای پیگیری مشکل پرداخت و فعال‌سازی اشتراک، لطفاً با پشتیبانی راستاد (@Rastad_support) در ارتباط باشید تا در اسرع وقت بررسی شود.",
  "intent": "support_request",
  "user_segment": "support_needed",
  "needs_human_support": true,
  "confidence": 0.6604,
  "chunks_used": ["vip_products.txt §2", "rastad_services.txt §1", "exchange_signup.txt §1", "kol_program.txt §0"],
  "llm_provider": "openrouter",
  "fallback_used": false,
  "latency": { "total_ms": 1890, "llm_ms": 1610, "embedding_ms": 275, "other_ms": 5 }
}
```

**Empty message — expect `400 Bad Request`**
```bash
curl -s -X POST http://localhost:8000/api/message \
  -H "Content-Type: application/json" \
  -d '{"name": "Test", "message": ""}' | jq
```
Example response (HTTP 400) — the DRF serializer rejects it before the pipeline runs:
```json
{ "message": ["This field may not be blank."] }
```

**With explicit user_id**
```bash
curl -s -X POST http://localhost:8000/api/message \
  -H "Content-Type: application/json" \
  -d '{"user_id": 1, "name": "Ali", "message": "Trade Assist چیه؟"}' | jq
```

---

### GET /api/users

```bash
curl -s http://localhost:8000/api/users | jq
```
Example response:
```json
[
  { "user_id": 1, "name": "Ali",  "segment": "vip_interest",    "created_at": "2026-06-02T09:15:00Z", "last_seen_at": "2026-06-02T09:52:48Z" },
  { "user_id": 2, "name": "Sara", "segment": "exchange_signup", "created_at": "2026-06-02T09:20:11Z", "last_seen_at": "2026-06-02T09:48:03Z" }
]
```

---

### GET /api/users/{id}/messages

```bash
curl -s http://localhost:8000/api/users/1/messages | jq
```
Example response:
```json
[
  {
    "id": 12,
    "user_message": "خدمات VIP راستاد چیه؟",
    "assistant_reply": "اشتراک VIP راستاد دسترسی به سیگنال‌های اسپات و فیوچرز ...",
    "intent": "vip_question",
    "needs_human_support": false,
    "created_at": "2026-06-02T09:52:48Z"
  }
]
```

---

## Testing with Python

```python
import requests, json

BASE = "http://localhost:8000/api"

# Send a message
resp = requests.post(f"{BASE}/message", json={
    "name": "Ali",
    "message": "خدمات VIP راستاد چیه؟"
})
print(json.dumps(resp.json(), ensure_ascii=False, indent=2))

# List users
resp = requests.get(f"{BASE}/users")
print(json.dumps(resp.json(), ensure_ascii=False, indent=2))

# User message history
resp = requests.get(f"{BASE}/users/1/messages")
print(json.dumps(resp.json(), ensure_ascii=False, indent=2))
```

---

## Testing with Postman

A ready-to-use collection ships with the repo: **`rastad-api.postman_collection.json`**.
No manual request setup needed — import it and click Send.

### Import

1. Open Postman → **Import** → drag in `rastad-api.postman_collection.json`
   (or **Import → File → Upload**).
2. The collection **Rastad AI Assistant** appears in the sidebar with two folders:
   **Messages** and **Users**.

### What's inside

| Folder | Request | What it demonstrates |
|---|---|---|
| Messages | VIP Question | `vip_question` intent, KB-grounded reply |
| Messages | VIP Question — with user_id | reusing an existing user |
| Messages | Exchange Registration | `exchange_registration` intent |
| Messages | KOL Collaboration | `kol_collaboration` intent |
| Messages | Support Request — Payment Problem | `needs_human_support: true` |
| Messages | General Info | `general_info` intent |
| Messages | Trade Assist Question | KB retrieval for Trade Assist |
| Messages | 400 — Empty Message | validation error |
| Messages | 400 — Missing Message Field | validation error |
| Messages | No name — uses default | `name` defaults to `کاربر` |
| Users | List All Users | `GET /api/users` |
| Users | User Message History | `GET /api/users/{id}/messages` |

### Collection variables

The collection is pre-wired with two variables (edit under the collection's
**Variables** tab if needed):

| Variable | Default | Use |
|---|---|---|
| `base_url` | `http://localhost:8000` | server address — change if not running locally |
| `user_id` | `1` | used by the user-history and `with user_id` requests |

Start the stack (`docker compose up -d --build`), then send any request — the
defaults work out of the box.

---

## Architecture

### In one paragraph

A **monolithic Django app with strict internal layering** — one process, no
microservices, no queues. Each request flows through four layers, and **a layer
only ever talks to the layer directly below it**. The API layer handles HTTP and
validation only; the service layer owns all business logic and orchestration;
repositories own all database access; adapters wrap every external API (LLM and
embeddings) behind a small interface. External providers sit behind that adapter
boundary, so swapping OpenRouter for OpenAI, or HuggingFace for another embedder,
is a `.env` change with **zero service-layer edits**. The design favours code that
is easy to run, easy to explain, and easy to extend.

### Layered view

```
┌──────────────────────────────────────────────────────────────┐
│  CLIENT            curl · Postman · Python · (future web UI)   │
└───────────────────────────────┬──────────────────────────────┘
                                 │ HTTP / JSON
┌───────────────────────────────▼──────────────────────────────┐
│  API LAYER  (DRF)          views · serializers · urls         │
│  validate input · return HTTP — NO business logic             │
└───────────────────────────────┬──────────────────────────────┘
                                 │ Python calls
┌───────────────────────────────▼──────────────────────────────┐
│  SERVICE LAYER             MessagePipeline (orchestrator)     │
│  Classifier · Retriever · Evaluator · Generator               │
│  all rules, decisions, timing, logging, fallbacks             │
└───────┬───────────────────────────────────────┬──────────────┘
        │ DB access only                         │ external APIs only
┌───────▼────────────────────┐     ┌─────────────▼──────────────┐
│  REPOSITORY LAYER           │     │  ADAPTER LAYER              │
│  User · Message · Knowledge │     │  LLM  → OpenRouter/OpenAI/  │
│  (Django ORM + raw pgvector)│     │         mock                │
│                             │     │  Embed→ HuggingFace / mock  │
└───────┬────────────────────┘     └─────────────┬──────────────┘
        │                                         │
┌───────▼────────────────────┐     ┌─────────────▼──────────────┐
│  PostgreSQL + pgvector      │     │  OpenRouter · HuggingFace   │
│  users · messages · chunks  │     │  (external HTTP APIs)       │
└─────────────────────────────┘     └─────────────────────────────┘
```

### Request flow

```
User Message
    │
    ▼
[1] DRF Serializer — validate input  (400 if message empty)
    │
    ▼
[2] ClassifierService — LLM → intent + segment + needs_human  (1 JSON call)
    │  fallback: RuleBasedClassifier (Persian keyword matching)
    ▼
[3] RetrieverService — HuggingFace embed → pgvector cosine search → top-4 chunks
    │  fallback: embed fails → empty chunks → human handoff
    ▼
[4] EvaluatorService — three-signal confidence check:
    │  low KB similarity OR support_request intent OR LLM flagged → needs_human
    ▼
[5] GeneratorService — LLM generates Persian reply grounded in KB chunks
    │  fallback: best-matching chunk text, or handoff template
    ▼
[6] Persist to PostgreSQL (errors logged, never block the reply) + return response
```

> For a step-by-step walk-through of both the **boot/KB-indexing** phase and the
> **per-request** phase — with teaching notes on embeddings, cosine similarity,
> and the fallback chain — see [`docs/request-lifecycle.md`](docs/request-lifecycle.md).

### Layer rules

```
API View → Service → Repository → DB
API View → Service → Adapter    → External API
```

No layer skips a level. Views have zero business logic. Repositories never call
adapters; adapters never call repositories.

---

## LLM Mode — Real or Mock?

**By default this project uses real, live AI services — not a mock.** Out of the
box (`docker compose up`), every request makes real external API calls:

| Job | Real provider (default) | Model |
|---|---|---|
| Intent + segment classification | **OpenRouter** (live) | `qwen/qwen3-8b` |
| Reply generation | **OpenRouter** (live) | `qwen/qwen3-8b` |
| Embeddings (KB + query) | **HuggingFace** (live) | `intfloat/multilingual-e5-base` |

So the classification, semantic retrieval, and generated Persian replies you see
are produced by genuine models — the `latency.llm_ms` and `latency.embedding_ms`
fields in each response reflect real network round-trips.

**A mock mode also exists**, purely for tests and offline development. Setting
`LLM_PROVIDER=mock` (and/or `EMBEDDING_PROVIDER=mock`) swaps in deterministic,
keyword-based stubs that make **zero network calls** and need no API keys. This is
what the test suite uses so tests stay fast and hermetic. Mock is opt-in — it is
never used unless you explicitly set it in `.env`.

---

## Switching LLM Provider

All switching is done by editing `.env` only — no code changes ever needed.

---

### OpenRouter (default)

```env
LLM_PROVIDER=openrouter
LLM_API_KEY=sk-or-v1-...
LLM_MODEL=qwen/qwen3-8b
```

Get a free key at [openrouter.ai](https://openrouter.ai).
Other fast free models you can drop in:

```env
LLM_MODEL=mistralai/mistral-7b-instruct
LLM_MODEL=meta-llama/llama-3.1-8b-instruct:free
LLM_MODEL=google/gemma-3-4b-it:free
```

---

### OpenAI

```env
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
LLM_MODEL=gpt-4o-mini
```

Get a key at [platform.openai.com](https://platform.openai.com).
Recommended models:

```env
LLM_MODEL=gpt-4o-mini     # fast, cheap, good Persian
LLM_MODEL=gpt-4o          # best quality
LLM_MODEL=gpt-3.5-turbo   # cheapest
```

---

### Mock (no API, for tests)

```env
LLM_PROVIDER=mock
```

Deterministic keyword-based responses. No key needed. Used by the test suite.

---

### How to apply the change

After editing `.env`:

```bash
docker compose restart app
```

The app reads `.env` at startup — only the app container needs a restart, not the DB.

---

### Latency comparison

| Provider | Typical `llm_ms` | Cost |
|---|---|---|
| OpenRouter free tier | 30,000–160,000ms | Free (queue wait) |
| OpenRouter paid | 1,000–3,000ms | ~$0.001/req |
| OpenAI `gpt-4o-mini` | 800–2,000ms | ~$0.001/req |
| OpenAI `gpt-4o` | 1,000–4,000ms | ~$0.01/req |
| Mock | < 5ms | Free |

The `latency.llm_ms` field in every response tells you exactly how much time the LLM is costing per request.

---

## Running Tests

Tests use the mock LLM and a zero-vector embedding stub — no API keys or network needed.

```bash
# Requires a running DB (start with: docker compose up db -d)
docker compose exec app .venv/bin/pytest tests/ -v
```

Or locally with the venv:

```bash
docker compose up db -d
.venv/bin/pytest tests/ -v
```

---

## Known Limitations

These are conscious trade-offs for an MVP built on free tiers, stated honestly:

- **Free API tiers are slow and rate-limited.** The OpenRouter free tier queues
  requests (a single `llm_ms` can be **30–160 seconds** under load), and the
  HuggingFace free Inference API cold-starts the model on first use. The system
  is correct and stays up, but it is **not fast on free keys** — that is a budget
  limit, not an architecture limit. A paid key or a dedicated inference endpoint
  brings `llm_ms` down to ~1–3 s.
- **Embedding model is a small multilingual one** (`e5-base`, 768-dim) chosen for
  a free tier. It is decent on Persian but not state-of-the-art.
- **KB is static** — chunks are embedded at boot; adding/editing a file needs a
  re-index (`index_knowledge_base --force`) or a restart, not a live update.
- **No authentication** on the API — any caller can query any user's history.
- **Single instance** — no horizontal scaling, no connection pooling beyond
  Django defaults, no rate limiting.
- **No streaming** — the reply is returned as one complete string, not token-by-token.
- **Dev server** — runs Django's `runserver`, not a production WSGI server.
- **Placeholder knowledge base** — the Rastad KB content is illustrative, not real
  internal data.

---

## With More Time (Roadmap)

If this were taken past the MVP, in rough priority order:

**Speed & cost (the biggest win)**
- Move off free tiers to a **paid OpenRouter key or a dedicated/self-hosted
  inference endpoint** to cut `llm_ms` from tens of seconds to ~1–3 s.
- **Run classification and embedding concurrently** — they are independent of each
  other, so firing both at once would remove one round-trip from the critical path.
- **Cache embeddings of common queries** (Redis) and reuse them across users.
- **Stream the LLM reply** so the user sees text appear immediately.

**Better embeddings & retrieval**
- Upgrade to a **stronger multilingual embedding model**, or bundle a local
  `sentence-transformers` model into the image to remove the network dependency
  entirely (fully offline, no rate limits).
- **Incremental, live re-indexing** of the KB (a watch/endpoint) instead of a
  restart, and smarter chunking (overlap, headings) for larger documents.
- Add a **re-ranking** step over the top-K chunks for higher precision.

**Architecture & scale**
- Production serving with **gunicorn + workers** behind a reverse proxy.
- **DB connection pooling** (pgBouncer) and read replicas as traffic grows.
- Extract the LLM calls into **Celery + Redis** async workers so the API thread
  isn't blocked on a slow provider.
- At large vector counts, evaluate a **dedicated vector DB** (Qdrant/pgvector
  tuning) and HNSW indexes over `ivfflat`.

**Product & safety**
- **Authentication** (the deferred login/signup UI + session/user scoping) and
  **rate limiting** on the public API.
- The **single-page chat + inspector UI** described in `docs/ui-design.md`.
- Fix the test wiring so the suite is guaranteed hermetic (truly mock-only, no
  accidental live calls).
- Observability: structured request tracing and a latency dashboard.
