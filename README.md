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

**Exchange registration**
```bash
curl -s -X POST http://localhost:8000/api/message \
  -H "Content-Type: application/json" \
  -d '{"name": "Sara", "message": "چطور در صرافی ثبت نام کنم؟"}' | jq
```

**KOL collaboration**
```bash
curl -s -X POST http://localhost:8000/api/message \
  -H "Content-Type: application/json" \
  -d '{"name": "Reza", "message": "میخوام با راستاد همکاری KOL داشته باشم"}' | jq
```

**Support request — expect `needs_human_support: true`**
```bash
curl -s -X POST http://localhost:8000/api/message \
  -H "Content-Type: application/json" \
  -d '{"name": "Maryam", "message": "مشکل پرداخت دارم، اشتراکم فعال نشده"}' | jq
```

**Empty message — expect `400 Bad Request`**
```bash
curl -s -X POST http://localhost:8000/api/message \
  -H "Content-Type: application/json" \
  -d '{"name": "Test", "message": ""}' | jq
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

---

### GET /api/users/{id}/messages

```bash
curl -s http://localhost:8000/api/users/1/messages | jq
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

```
User Message
    │
    ▼
[1] DRF Serializer — validate input
    │
    ▼
[2] ClassifierService — LLM → intent + segment + needs_human
    │  fallback: RuleBasedClassifier (keyword matching)
    ▼
[3] RetrieverService — HuggingFace embed → pgvector cosine search → top-4 chunks
    │
    ▼
[4] EvaluatorService — three-signal confidence check:
    │  low KB similarity OR support_request intent OR LLM flagged
    ▼
[5] GeneratorService — LLM generates Persian reply grounded in KB chunks
    │  fallback: best matching chunk or handoff template
    ▼
[6] Persist to PostgreSQL + return response
```

### Layer rules

```
API View → Service → Repository → DB
API View → Service → Adapter    → External API
```

No layer skips a level. Views have zero business logic.

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

- **No authentication** on API endpoints — any caller can query any user's history
- **Single instance** — no horizontal scaling, no connection pooling beyond Django defaults
- **KB is static** — re-embed after changing knowledge base files requires restart
- **No streaming** — LLM reply returned as a complete string, not streamed
- **Dev server** — uses Django's `runserver`, not production-grade (gunicorn is the next step)
