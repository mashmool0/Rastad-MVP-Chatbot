# Design Decisions — Rastad AI Assistant

Each entry follows the same structure:
**Context → Options → Decision → Why → Trade-off accepted**

---

## 1. Django + DRF over FastAPI

**Context:** The task lists FastAPI first, Django second. Both are valid.

**Options:**
- FastAPI — lightweight, async-native, automatic OpenAPI docs, faster for pure APIs
- Django + DRF — batteries-included, ORM + migrations + auth + serializers built-in

**Decision:** Django + DRF

**Why:**
- Built-in auth (`django.contrib.auth`) covers login/signup with zero extra work
- DRF serializers give free input validation — a scored criterion
- ORM + migrations handle the multi-model schema cleanly
- Faster implementation time when the developer knows Django well

**Trade-off accepted:**
For a high-concurrency async service, FastAPI would be the right choice.
Django's sync ORM becomes a bottleneck at scale. Acknowledged in README limitations.

---

## 2. PostgreSQL + pgvector over a Separate Vector DB

**Context:** The task awards bonus points for using a vector DB (FAISS, Chroma, Qdrant).

**Decision:** pgvector inside PostgreSQL

**Why:**
- Zero additional infrastructure — one DB, one Docker service, one connection string
- Operational simplicity: no second container to manage
- Django ORM integration via `pgvector.django`
- For MVP scale (4 KB files, ~23 chunks), performance is identical to Qdrant

**Trade-off accepted:**
At large scale (millions of vectors), a dedicated vector DB outperforms pgvector.

---

## 3. Jina AI for Embeddings (not OpenRouter)

**Context:** Original plan called for OpenRouter for both LLM and embeddings.

**Options:**
- OpenRouter — planned, but has no embeddings endpoint (chat completions only)
- Jina AI — free hosted, multilingual, 1024-dim, simple REST API
- Local sentence-transformers — offline, no API key, but requires Docker image to bundle model
- OpenAI embeddings — 1536-dim, needs separate key and cost

**Decision:** Jina AI (`jina-embeddings-v3`, dim 1024)

**Why:**
- OpenRouter doesn't expose an embeddings endpoint — discovered at implementation
- Jina free tier is generous (1M tokens), no credit card required
- Strong Persian multilingual support
- `EMBEDDING_DIM=1024` is read from settings — dimension not hardcoded

**Trade-off accepted:**
Two API providers instead of one. Mitigated by the adapter pattern —
swapping Jina for another provider changes only `adapters/embedding/`.

---

## 4. Multiple LLM Provider Support via `.env`

**Context:** Initially only OpenRouter was planned. OpenAI adapter was added after.

**Options:**
- Hard-code one provider
- Support multiple providers through an adapter + factory pattern

**Decision:** Adapter pattern with factory routing by `LLM_PROVIDER` env var

**Why:**
- `adapters/factory.py` reads `LLM_PROVIDER` at startup and returns the right adapter
- Adding a new provider = one new file in `adapters/llm/`, one `if` in factory
- Zero service layer or pipeline changes for any provider switch
- User switches provider by editing `.env` and restarting — no code knowledge needed

**Currently supported:** `openrouter` (default), `openai`, `mock`

---

## 5. One LLM Call for Classification (Not Two)

**Context:** We need intent, segment, and needs_human_support for every message.

**Decision:** One call, structured JSON output, Pydantic-validated

**Why:**
- Halves LLM API calls per request — lower latency, lower cost
- The model can reason about all three together
- Pydantic validation with retry handles reliability
- EvaluatorService adds KB-confidence as a second signal on top

**Trade-off accepted:**
A single prompt asking for three things is slightly harder to tune than three focused prompts.
Mitigated by clear enum constraints in the prompt and retry logic.

---

## 6. Pydantic Validation + Retry + Thinking Block Stripping

**Context:** LLMs don't always return valid structured JSON on the first try.
Qwen3-8b also outputs `<think>…</think>` reasoning blocks before its answer.

**Decision:** Pydantic + retry (max 2) + `_strip_thinking()` + rule-based fallback

**Why:**
- Silent failures produce wrong intent/segment stored in DB — corrupts analytics
- Thinking blocks in Qwen3-8b must be stripped before JSON parsing and before
  returning the generation reply to the user
- Retry with Persian error feedback works well with instruction-following models
- Rule-based fallback guarantees the system always returns a valid `ClassificationResult`

**`_strip_thinking()` applied to:**
- Classification output — before `json.loads()` 
- Generation output — before returning the reply string

---

## 7. Confidence Threshold for needs_human_support

**Decision:** Three-signal combination in EvaluatorService

```python
needs_human = (
    max(similarity) < CONFIDENCE_THRESHOLD  # KB can't answer this
    or intent == "support_request"           # user has a problem
    or llm.needs_human_support               # LLM flagged it
)
```

`CONFIDENCE_THRESHOLD = 0.45` — configurable via `.env`.

**Why:**
- A question the KB can't answer confidently should go to a human
- Combining three independent signals reduces false positives and false negatives

---

## 8. Nullable `auth_user` on RastadUser

**Context:** Original spec required a non-null `OneToOneField` to `auth.User`.
The open API (`POST /api/message`) needs to create users without a login account.

**Decision:** `auth_user = OneToOneField(null=True, blank=True)`

**Why:**
- The API is open — any caller supplies a `user_id` or gets one auto-assigned
- Requiring a Django auth account for API users would break the core endpoint
- The UI login/signup flow (2nd pass) links a `auth.User` after the fact
- `auth_user=None` for API-created users, non-null for signup-created users

---

## 9. Per-Step Latency Breakdown

**Context:** Initial response had only `latency_ms` (total). Hard to diagnose slowness.

**Decision:** Three timing buckets in every response and log line

```json
"latency": {
  "total_ms": 2100,
  "llm_ms": 1750,
  "embedding_ms": 290,
  "other_ms": 60
}
```

**Why:**
- LLM free tier queuing (30–160 seconds) vs Jina latency (1–2 seconds) need
  to be visible separately — they have different optimization paths
- `llm_ms` points to provider choice, `embedding_ms` to Jina plan, `other_ms` to DB

---

## 10. Paragraph Chunking over Fixed-Token Sliding Window

**Decision:** Paragraph splitting on `\n\n`

**Why:**
- KB files are short and author-controlled
- Each paragraph covers one atomic topic
- No overlap needed
- Content hash per chunk enables idempotent re-indexing

**Trade-off accepted:**
Paragraph size is inconsistent. At production scale with large documents,
fixed-token + overlap is better.

---

## 11. Docker Compose Port 5433 for DB

**Context:** Local PostgreSQL installations typically occupy port 5432.

**Decision:** Map the DB container to `5433:5432`

**Why:**
- Avoids port conflict with system Postgres — both can run simultaneously
- App container connects internally via `db:5432` (Docker network, no conflict)
- Local `manage.py` connects via `localhost:5433`
- pgvector is pre-installed in `pgvector/pgvector:pg16` — no system `apt install` needed

---

## 12. Django App Label Conflict — `rastad_messages`

**Context:** `apps.messages` conflicts with Django's built-in `django.contrib.messages`.

**Decision:** Set `label = "rastad_messages"` in `apps/messages/apps.py`

**Why:**
- Django raises `ImproperlyConfigured` if two apps share the same label
- Renaming the app directory would break the project layout convention
- A custom label resolves it cleanly with one line
- Migrations use `rastad_messages` as the app label internally
