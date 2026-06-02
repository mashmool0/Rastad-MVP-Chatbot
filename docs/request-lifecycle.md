# Request Lifecycle — Complete Technical Scenario (with teaching notes)

This document follows the system end to end, twice:

1. **Part A — Boot:** what happens when the container starts and embeds the
   knowledge base *before* any request can be served.
2. **Part B — Request:** what happens from the moment a user sends a message to
   the moment they receive a response.

Every layer, every external call, every decision — plus short **💡 teaching
boxes** that explain *why* a step exists, not just *what* it does.

The provider in use is **HuggingFace** for embeddings
(`intfloat/multilingual-e5-base`, **768-dim**) and **OpenRouter** for the LLM
(`qwen/qwen3-8b`). Both are swappable via `.env` with zero service-layer changes.

---

# Part A — Server Boot & Knowledge Base Embedding

> **Why this part matters:** retrieval at request time can only find a chunk if
> that chunk was embedded *with the same model and dimension* at boot. The boot
> phase is not a warm-up — it is the step that makes search possible at all. If
> boot embeds with the wrong model (or the mock zero-vector stub), every later
> request silently returns "no chunks" and falls back to a human handoff.

## A.0 — The entrypoint chain

`entrypoint.sh` runs four steps in strict order. Each must succeed before the
next begins (`set -e` aborts the container on any failure).

```
┌─────────────────────────────────────────────────────────────┐
│ 1. Wait for PostgreSQL    (socket probe, up to 30 × 1s)      │
│ 2. Run migrations         (python manage.py migrate)         │
│ 3. Index knowledge base   (python manage.py index_knowledge_base) │
│ 4. Start server           (runserver 0.0.0.0:8000)           │
└─────────────────────────────────────────────────────────────┘
```

```bash
# entrypoint.sh (essence)
wait_for_postgres()                 # socket.create_connection((DB_HOST, DB_PORT))
python manage.py migrate --noinput
python manage.py index_knowledge_base
exec python manage.py runserver 0.0.0.0:8000
```

Boot logs:
```
[BOOT] Waiting for PostgreSQL at db:5432...
[BOOT] PostgreSQL is up.
[BOOT] Running migrations...
[BOOT] Indexing knowledge base...
[INFO ] BOOT | Knowledge base indexed — 0 new, 23 unchanged, 23 total chunks
[BOOT] Starting server...
```

> 💡 **Why wait for Postgres first?** In Docker Compose the `db` and `app`
> containers start in parallel. The app's first action is a DB connection, so it
> polls a raw TCP socket (not Django) for up to 30 seconds. This avoids a
> crash-loop race where the app dies because Postgres hasn't finished its own
> startup. `depends_on: condition: service_healthy` in compose plus this probe
> are belt-and-suspenders.

---

## A.1 — Migrations (the pgvector column)

`migrate` applies the `knowledge` app migrations in order:

| Migration | What it does |
|---|---|
| `0001_enable_pgvector` | `CREATE EXTENSION IF NOT EXISTS vector;` |
| `0002_initial` | create `knowledge_chunks` table |
| `0003_add_vector_index` | `ivfflat` index on `embedding` (`lists = 10`) |
| `0004_change_embedding_dim_768` | `ALTER COLUMN embedding TYPE vector(768)` + state sync |

> 💡 **The `0004` state-sync subtlety.** A `RunSQL` migration changes the
> *database* but not Django's *migration state graph* (Django's mental model of
> what the schema should be). `0004` therefore carries a `state_operations=[…
> AlterField(dimensions=settings.EMBEDDING_DIM)]` so Django's recorded state
> matches the SQL it ran. Without it, every boot prints *"models in app
> 'knowledge' have changes not yet reflected in a migration"* even though the
> column is already correct. `state_operations` means "treat the SQL as
> equivalent to this ORM op for state purposes; don't re-run anything."

The column is `vector(768)` because `EMBEDDING_DIM=768` and that is the output
width of `intfloat/multilingual-e5-base`. **The column width must equal the model
output width**, or every insert/search errors.

---

## A.2 — Indexing: file → chunk → embed → store

`python manage.py index_knowledge_base` reads every `knowledge_base/*.txt` file
and turns it into searchable rows. The command is **idempotent** — safe to run on
every boot.

### Step 1 — Chunk

```
read file  →  strip whitespace
           →  split on "\n\n"          (one paragraph = one chunk)
           →  drop chunks shorter than 20 chars
           →  index them 0, 1, 2, …
```

```python
paragraphs = [p.strip() for p in raw.split("\n\n")]
chunks = [p for p in paragraphs if len(p) >= 20]
```

> 💡 **Why paragraph chunks (not fixed-size windows)?** The KB files are short and
> author-controlled — each paragraph is one atomic topic (one VIP tier, one
> signup step). Paragraph boundaries are natural semantic boundaries, so no
> overlap or token-window machinery is needed. At production scale with long
> documents you'd switch to fixed-token + overlap; here it would only add noise.

### Step 2 — Hash & decide

```python
content_hash = hashlib.md5(content.encode()).hexdigest()
existing = repo.get_existing(source_file, chunk_index)
if not force and existing and existing.content_hash == content_hash:
    skipped += 1          # unchanged → no API call
    continue
```

> 💡 **Why an MD5 content hash?** Embedding costs an API call. The hash lets the
> indexer skip any chunk whose text is byte-for-byte unchanged since last time, so
> a restart re-embeds *only* new or edited paragraphs. The hash is the idempotency
> key, scoped per `(source_file, chunk_index)`.

### Step 3 — Embed (HuggingFace, the network call)

```python
embedding = embedder.embed(content, task="retrieval.passage")
```

The HuggingFace adapter sends:

```
POST https://router.huggingface.co/hf-inference/models/intfloat/multilingual-e5-base/pipeline/feature-extraction
Authorization: Bearer hf_...
Content-Type: application/json
{ "inputs": "passage: اشتراک VIP راستاد …", "options": { "wait_for_model": true } }
```

Response: a flat **768-float list** — the meaning of that paragraph as a point in
768-dimensional space:

```python
[0.0318, 0.0456, -0.0104, …, 0.0119]   # 768 numbers
```

> 💡 **What is an embedding?** A function that maps text to a fixed-length vector
> such that *texts with similar meaning land near each other*. "خدمات VIP" and
> "اشتراک ویژه" point in almost the same direction even though they share no
> letters. This is what makes semantic search possible — we compare *meanings*,
> not keywords.

> 💡 **Why the `passage:` / `query:` prefixes?** The e5 family is an *asymmetric*
> retrieval model: documents are embedded with a `passage: ` prefix and search
> queries with a `query: ` prefix. The adapter maps the port's `task` argument to
> the prefix — `task="retrieval.passage"` at index time, `task="retrieval.query"`
> at search time. Mismatching them measurably degrades relevance.

> 💡 **What is `router.huggingface.co`?** HuggingFace's Inference API is now a
> *provider router*. The path encodes the provider (`hf-inference`) and the exact
> pipeline (`/pipeline/feature-extraction`). The older `api-inference.huggingface.co`
> host was decommissioned — pointing at it fails DNS resolution before any
> request leaves the machine. (This was the embedding bug that took the system
> down: a dead hostname plus chunks left as zero-vectors. See A.4.)

**Cold-start handling.** On the free tier the model may be unloaded; the API
returns `503` with an `estimated_time`. The adapter waits and retries up to 3
times:

```
[WARNING] EMBED | HuggingFace model loading, waiting 12s (attempt 1)
```

### Step 4 — Store (upsert)

```python
KnowledgeChunk.objects.update_or_create(
    source_file=source_file, chunk_index=chunk_index,
    defaults={"content": content, "content_hash": content_hash, "embedding": embedding},
)
```

`unique_together = (source_file, chunk_index)` makes this a true upsert — re-running
overwrites a changed paragraph in place rather than duplicating it.

Final boot log:
```
[INFO] BOOT | Knowledge base indexed — N new, M unchanged, T total chunks
```

---

## A.3 — Re-embedding on purpose: `--force`

```bash
python manage.py index_knowledge_base --force
```

`--force` ignores the hash-skip and re-embeds **every** chunk. Use it whenever the
*embedding provider, model, or dimension changes* — because then the stored
vectors are stale even though the text is identical, and the hash would otherwise
skip them forever.

```
[INFO] BOOT | Knowledge base indexed — 23 new, 0 unchanged, 23 total chunks
```

---

## A.4 — ⚠️ The invariant that ties boot to every request

> **The query vector and the stored chunk vectors must come from the same model,
> the same dimension, and compatible prefixes.** Break any of the three and
> retrieval silently returns nothing useful:
>
> | Broken invariant | Symptom at request time |
> |---|---|
> | Wrong dimension (e.g. 1024 stored vs 768 query) | insert/search errors, `chunks=0` |
> | Stored as **mock zero-vectors** | `<=>` cosine vs a zero vector is undefined → `chunks=0`, `confidence=0.0` |
> | Different model than query | vectors live in different spaces → low/garbage similarity |
>
> Because the pipeline degrades gracefully, the user still gets HTTP 200 — but
> the inspector shows `confidence=LOW` and a human-handoff reply on *every*
> message. The tell in the logs is `RETRIEVE | chunks=0` on requests that should
> clearly have matched the KB. The fix is always `index_knowledge_base --force`
> with the correct provider configured.

---

# Part B — Request Lifecycle

**Example input:**
```json
{ "name": "Ali", "message": "خدمات VIP راستاد چیه؟" }
```

The pipeline object is built **once at import time** (`apps/api/views.py` →
`build_pipeline()`), so adapters and repositories are wired and reused across
requests — no per-request construction.

---

## Phase 0 — HTTP arrives at Django

The POST hits `rastad/wsgi.py`. Django middleware runs in order
(Security → Session → Common → Csrf → Authentication → Message), then URL routing
resolves `/api/message` → `apps/api/urls.py` → `message_view`.

---

## Phase 1 — Input validation (DRF serializer)

`MessageRequestSerializer(data=request.data)`:

| Field | Rule | Result |
|---|---|---|
| `user_id` | optional integer, nullable | `None` if missing |
| `name` | optional string | defaults to `"کاربر"` |
| `message` | required, `min_length=1` | **400 if empty or missing** |

If invalid → **400 immediately, the pipeline never runs.**
If valid → `validated_data = {"user_id": None, "name": "Ali", "message": "خدمات VIP…"}`.

> 💡 **Why validate in a serializer, not the view?** Views stay logic-free
> (Layer Law). The serializer is the single, declarative place input shape is
> enforced, and it produces a clean `400` without touching the pipeline.

---

## Phase 2 — Pipeline starts, timer begins

```python
t0 = time.monotonic()
MessagePipeline.process(user_id=None, name="Ali", message="خدمات VIP راستاد چیه؟")
```
```
[INFO] REQUEST | user_id=None message_len=21
```

> 💡 **Why `time.monotonic()` (not `time.time()`)?** Monotonic time never jumps
> backward (NTP adjustments, DST). For measuring *durations* it is the correct
> clock; wall-clock time is only used for the human-readable `timestamp` field.

---

## Phase 2a — User resolution

`UserRepository.get_or_create(user_id=None, name="Ali")`

- `user_id` is `None` → `RastadUser.objects.create(name="Ali")`, Postgres assigns
  `user_id` (e.g. `3`), `auth_user=NULL` (open-API user, no login account).

```
[INFO] REQUEST | new user created user_id=3 name=Ali
```

---

## Phase 2b — Classification — LLM call #1 (network)

`ClassifierService.classify("خدمات VIP راستاد چیه؟")`

### The request to OpenRouter
```
POST https://openrouter.ai/api/v1/chat/completions   (temperature=0.3, timeout=30s)
messages = [ {system: "تو یک سیستم دسته‌بندی…"}, {user: "خدمات VIP راستاد چیه؟"} ]
```

The single system prompt asks for **all three fields at once** as strict JSON:
`intent`, `segment`, `needs_human_support`.

> 💡 **Why one call for three fields?** It halves latency and cost versus three
> prompts, and lets the model reason about intent/segment/urgency together. The
> reliability cost (one prompt doing three jobs) is paid back by Pydantic
> validation + retry below.

### Processing the raw reply
Qwen3-8b returns an optional `<think>…</think>` reasoning block then the JSON:
```
<think> The user asks about VIP services… intent=vip_question … </think>
{"intent":"vip_question","segment":"vip_interest","needs_human_support":false}
```
The adapter runs:
1. `_strip_thinking()` — regex-removes `<think>…</think>` (DOTALL).
2. `_extract_json()` — regex `\{.*\}` finds the JSON object.
3. `json.loads()` → dict.
4. `ClassificationResult(**data)` — Pydantic validates both enums.

> 💡 **What is the `<think>` block?** Qwen3 has an extended-thinking mode and
> emits its chain-of-thought before the answer. That reasoning happens on
> OpenRouter's GPUs, not locally. We strip it before JSON parsing *and* before
> showing any generated reply to the user — otherwise raw reasoning would leak
> into both.

### Reliability: retry then fall back
- **Invalid JSON / failed enum validation** → retry (max 2, so 3 attempts total)
  with the validation error injected back into the prompt (`_RETRY_TEMPLATE`,
  in Persian). Still failing → the adapter raises `LLMError`.
- **`LLMError` (network/HTTP failure, or retries exhausted)** → `ClassifierService`
  catches it and runs `RuleBasedClassifier` (Persian keyword map), tagging
  `source="rule_based"` and forcing `needs_human_support=True` for support hits.

```
[INFO] CLASSIFY | intent=vip_question  segment=vip_interest  needs_human=False source=llm latency_ms=820
```
On fallback:
```
[WARNING] FALLBACK | LLM classify failed — using rule-based classifier: …
[INFO]    CLASSIFY | intent=vip_question  segment=vip_interest  needs_human=False source=rule_based latency_ms=…
```

> 💡 **Why a rule-based fallback at all?** It guarantees the function's
> contract — it *always* returns a valid `ClassificationResult`. The system stays
> up even with the LLM fully offline; it just becomes less nuanced and routes
> more cases to a human.

---

## Phase 2c — Retrieval — embed + pgvector

`RetrieverService.retrieve("خدمات VIP راستاد چیه؟")`

### Step 1 — Embed the query (HuggingFace, network)
```python
vector = embedder.embed(message, task="retrieval.query")   # "query: خدمات VIP…"
```
Same router endpoint as boot, but with the `query:` prefix → a **768-dim** vector.

If embedding raises `EmbeddingError`, the service swallows it and returns `[]`:
```
[WARNING] FALLBACK | embedding failed — skipping retrieval: …
```
Downstream this means `max_similarity=0.0` → `needs_human=True`.

### Step 2 — Similarity search (pgvector, local DB, no network)
```sql
SELECT content, source_file, chunk_index,
       1 - (embedding <=> %s::vector) AS similarity
FROM knowledge_chunks
ORDER BY embedding <=> %s::vector
LIMIT 4;            -- RETRIEVE_TOP_K
```

> 💡 **What is `<=>` and why `1 - distance`?** `<=>` is pgvector's **cosine
> distance** — the angle between two vectors (0 = identical direction, 2 =
> opposite). Cosine compares *direction*, i.e. meaning, ignoring magnitude. We
> report `similarity = 1 - distance` so **higher = more relevant**, which is the
> intuitive scale for the threshold and the UI bar.

> 💡 **What is the `ivfflat` index doing?** It clusters the stored vectors into
> `lists` buckets so search probes only nearby buckets instead of scanning all
> rows — approximate nearest-neighbour, much faster at scale. With ~23 vectors
> it's overkill, but it's the same code path production would use.

```
[INFO] RETRIEVE | chunks=4 top_similarity=0.88 latency_ms=290
[INFO] CHUNK[1] | vip_products.txt §1 similarity=0.8800 | اشتراک VIP راستاد …
[INFO] CHUNK[2] | rastad_services.txt §2 similarity=0.74 | …
[INFO] CHUNK[3] | vip_products.txt §2 similarity=0.71 | …
[INFO] CHUNK[4] | kol_program.txt §2 similarity=0.66 | …
```

---

## Phase 2d — Evaluation (pure logic, no API calls)

`EvaluatorService.evaluate(chunks, classification)` collects **reasons** from three
independent signals; `needs_human = any reason present`:

```python
max_similarity = max((c.similarity for c in chunks), default=0.0)
reasons = []
if max_similarity < CONFIDENCE_THRESHOLD:      reasons.append("low_confidence")        # 0.45
if intent == "support_request":                reasons.append("support_request_intent")
if classification.needs_human_support:         reasons.append("llm_flagged")
needs_human = bool(reasons)
```

Confidence label (for logs/UI): `HIGH ≥ 0.7`, `MEDIUM ≥ 0.45`, else `LOW`.

> 💡 **Why three signals instead of one?** Each catches a different failure mode:
> the KB *can't* answer (low similarity), the user *has a problem* (support
> intent), or the model itself *asked for a human* (urgent/angry/off-topic).
> Combining independent signals lowers both false handoffs and missed handoffs.

```
[INFO] EVALUATE | needs_human=False confidence=HIGH similarity=0.88 threshold=0.45 reason=none
```
When triggered:
```
[WARNING] EVALUATE | needs_human=True confidence=LOW similarity=0.31 threshold=0.45 reason=low_confidence,llm_flagged
```

---

## Phase 2e — Generation — LLM call #2 (network, usually)

`GeneratorService.generate(message, chunks, intent, needs_human)`

**Shortcut (no LLM call):** if `needs_human and not chunks` → return the hardcoded
Persian handoff template, `fallback_used=False` (it's intentional, not a failure):
```
متأسفم، در حال حاضر اطلاعات کافی برای پاسخ به این سوال ندارم.
تیم پشتیبانی راستاد در اسرع وقت با شما تماس می‌گیرد.
```

**Normal path:** the top chunk texts are injected as grounding context:
```
SYSTEM: تو دستیار هوشمند پشتیبانی راستاد هستی … (فقط از اطلاعات داده‌شده استفاده کن، حداکثر ۳ جمله)

--- اطلاعات راستاد ---
{chunk_1}

{chunk_2}
----------------------

نوع درخواست: vip_question

پیام کاربر: خدمات VIP راستاد چیه؟
```
The reply runs through `_strip_thinking()` before returning.

**If the LLM call fails (`LLMError`):** fall back to the first chunk's text as the
reply (or the handoff template if no chunks), `fallback_used=True`:
```
[WARNING] FALLBACK | LLM generate failed — using template reply: …
```

> 💡 **Why a *second* LLM call?** Call #1 produced structured *data*
> (intent/segment/flag). Call #2 produces *prose* — the grounded Persian answer.
> Different jobs, different prompts. Grounding it in retrieved chunks is what
> keeps the reply about *Rastad's actual* offering instead of generic model
> knowledge.

```
[INFO] GENERATE | provider=openrouter model=qwen/qwen3-8b fallback=False latency_ms=930
```

---

## Phase 2f — Latency buckets & structured payload

```python
llm_ms       = (classify) + (generate)
embedding_ms = (classify → retrieve)     # Jina/HF embed + pgvector search
other_ms     = (t0 → user) + (retrieve → evaluate)
total_ms     = (t0 → now)
```

> 💡 **Why split latency into three buckets?** They have different fixes. High
> `llm_ms` → provider/model or free-tier queueing (can be 30–200s). High
> `embedding_ms` → embedding API or a cold DB connection. High `other_ms` → the
> database. One number can't tell you which knob to turn.

```
[INFO]  DONE    | llm_ms=1750 embedding_ms=290 other_ms=5 total_ms=2045
[DEBUG] PAYLOAD | {"timestamp":…, "intent":"vip_question", "confidence":"HIGH", "chunks_used":[…], "latency_breakdown":{…}, "error":null}
```
The full structured payload is logged **at DEBUG only**, and never contains the
message text — only metadata (Layer Law / privacy rule).

---

## Phase 2g — Persist (never fails the response)

```python
try:
    message_repo.save(user, message, reply, intent, needs_human)
    user_repo.update_last_seen_and_segment(user, segment)
except Exception as e:
    logger.error("DB | failed to save message: %s", e)   # logged, NOT raised
```

> 💡 **Why swallow DB errors here?** The user already has a good answer in hand. A
> storage hiccup must not turn a successful conversation into a 500. We log it at
> ERROR for ops and still return the reply.

---

## Phase 3 — Response

```
[INFO] DONE | llm_ms=1750 embedding_ms=290 other_ms=5 total_ms=2045
```
```json
{
  "reply": "اشتراک VIP راستاد دسترسی به سیگنال‌های اسپات و فیوچرز …",
  "intent": "vip_question",
  "user_segment": "vip_interest",
  "needs_human_support": false,
  "confidence": 0.8766,
  "chunks_used": ["vip_products.txt §1","rastad_services.txt §2","vip_products.txt §2","kol_program.txt §2"],
  "llm_provider": "openrouter",
  "fallback_used": false,
  "latency": { "total_ms": 2045, "llm_ms": 1750, "embedding_ms": 290, "other_ms": 5 }
}
```

---

## Failure matrix (every path returns *something*)

```
┌──────────────────────┬───────────────────────────────────┬──────────────────────────────┐
│ Failure              │ What runs instead                 │ User sees                    │
├──────────────────────┼───────────────────────────────────┼──────────────────────────────┤
│ LLM classify fails   │ RuleBasedClassifier (keywords)    │ Reply, needs_human=True      │
│ JSON invalid ×3      │ → LLMError → RuleBasedClassifier  │ Reply, needs_human=True      │
│ HF embed fails       │ chunks=[], skip pgvector          │ Handoff template             │
│ similarity < 0.45    │ EvaluatorService flags it         │ Handoff template             │
│ LLM generate fails   │ First chunk text as reply         │ Chunk text, fallback=True    │
│ DB write fails       │ Error logged, response unaffected │ Full reply still returned    │
└──────────────────────┴───────────────────────────────────┴──────────────────────────────┘
```

The principle throughout: **degrade gracefully, always return something, always
log the reason.**

---

## External calls — summary

| Call | Provider | When | Skipped if |
|---|---|---|---|
| Classification | OpenRouter (Qwen3-8b) | every request | `LLM_PROVIDER=mock` |
| Query embedding | HuggingFace (e5-base) | every request | `EMBEDDING_PROVIDER=mock` |
| Generation | OpenRouter (Qwen3-8b) | every request except the no-chunks handoff | `LLM_PROVIDER=mock` |
| Passage embedding | HuggingFace (e5-base) | **boot only**, per new/changed chunk | `EMBEDDING_PROVIDER=mock` or unchanged hash |

Max 3 external calls per request (classify + embed + generate); 0 in mock mode.
Boot makes one embedding call per new/changed chunk (none on a warm restart).
