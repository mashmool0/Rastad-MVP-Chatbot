# Request Lifecycle — Complete Technical Scenario

What happens internally from the moment a user sends a message to the moment
they receive a response. Every layer, every API call, every decision.

**Example input:**
```json
{ "name": "Ali", "message": "خدمات VIP راستاد چیه؟" }
```

---

## Phase 0 — HTTP arrives at Django

The HTTP POST hits Django's WSGI handler (`rastad/wsgi.py`).
Django's middleware stack runs in sequence:

```
SecurityMiddleware
  → SessionMiddleware
  → CommonMiddleware
  → CsrfViewMiddleware
  → AuthenticationMiddleware
  → MessageMiddleware
```

Django matches `/api/message` against `rastad/urls.py` → `apps/api/urls.py`
→ resolves to the `message_view` function.

---

## Phase 1 — Input validation (DRF Serializer)

`MessageRequestSerializer(data=request.data)` runs three field checks:

| Field | Rule | Result |
|---|---|---|
| `user_id` | optional integer | `None` if missing |
| `name` | optional string | defaults to `"کاربر"` if missing |
| `message` | required, min_length=1 | **400 if empty or missing** |

If any field fails → **pipeline never runs, 400 returned immediately.**

If valid → `validated_data = {"user_id": None, "name": "Ali", "message": "خدمات VIP..."}`

---

## Phase 2 — Pipeline starts, timer begins

```python
t0 = time.monotonic()
```

`MessagePipeline.process(user_id=None, name="Ali", message="خدمات VIP راستاد چیه؟")`

Logged:
```
[INFO] REQUEST | user_id=None message_len=21
```

---

## Phase 2a — User resolution

`UserRepository.get_or_create(user_id=None, name="Ali")`

- `user_id` is `None` → no lookup → `RastadUser.objects.create(name="Ali")`
- PostgreSQL inserts into `rastad_users`, auto-assigns `user_id=3`
- `auth_user=NULL` — no Django login account linked (open API user)
- Returns the `RastadUser` object

```sql
INSERT INTO rastad_users (name, segment, created_at, last_seen_at)
VALUES ('Ali', 'new_user', now(), now())
RETURNING user_id;  -- returns 3
```

Logged:
```
[INFO] REQUEST | new user created user_id=3 name=Ali
```

---

## Phase 2b — Classification — LLM call #1 (goes to internet)

`ClassifierService.classify("خدمات VIP راستاد چیه؟")`

### Why this goes to the internet

The LLM (Qwen3-8b) runs on OpenRouter's GPU servers — not locally.
We send the message there because:
- It understands Persian language naturally and in context
- A keyword match would miss "قیمت اشتراک چنده؟" as a VIP question
- One call returns all three fields: intent + segment + needs_human

### What is the "thinking" part

Qwen3-8b has extended thinking mode. Before answering, it internally
reasons about the message and writes a `<think>` block — all of this
happens on OpenRouter's servers, not your machine. We strip it before parsing.
This is normal model behavior — the thinking is just server-side chain-of-thought.

**HTTP POST sent to OpenRouter:**
```
POST https://openrouter.ai/api/v1/chat/completions
Authorization: Bearer sk-or-v1-...
{
  "model": "qwen/qwen3-8b",
  "temperature": 0.3,
  "messages": [
    {"role": "system", "content": "تو یک سیستم دسته‌بندی هوشمند..."},
    {"role": "user",   "content": "خدمات VIP راستاد چیه؟"}
  ]
}
```

**Raw response from Qwen3-8b:**
```
<think>
The user is asking about VIP services of Rastad platform...
intent should be vip_question, segment vip_interest...
</think>
{"intent": "vip_question", "segment": "vip_interest", "needs_human_support": false}
```

**Processing steps:**
1. `_strip_thinking()` — removes the `<think>…</think>` block entirely
2. `_extract_json()` — regex finds `{…}` in the remaining text
3. `json.loads()` — parses to Python dict
4. `ClassificationResult(**data)` — Pydantic validates both fields against `Literal` enums

**If Pydantic validation fails** (wrong value in enum):
- Retry 1: rebuild prompt with Persian error injection + the validation error
- Retry 2: stricter instruction
- Still fails after 2 retries → `RuleBasedClassifier` runs (keyword matching, no internet)
- `needs_human_support` forced to `True`, log `WARNING FALLBACK`

**Result this time:**
```python
ClassificationResult(
    intent="vip_question",
    segment="vip_interest",
    needs_human_support=False
)
source = "llm"
```

Logged:
```
[INFO] CLASSIFY | intent=vip_question  segment=vip_interest  needs_human=False source=llm latency_ms=820
```

---

## Phase 2c — Retrieval — Embedding + pgvector (goes to internet for embed)

`RetrieverService.retrieve("خدمات VIP راستاد چیه؟")`

### Step 1 — Embed the message (Jina AI)

**HTTP POST sent to Jina AI:**
```
POST https://api.jina.ai/v1/embeddings
Authorization: Bearer jina_...
{
  "model": "jina-embeddings-v3",
  "input": ["خدمات VIP راستاد چیه؟"],
  "task": "retrieval.query"
}
```

`task="retrieval.query"` tells Jina this is a search query, not a document.
Jina returns a **1024-dimensional float vector** — the mathematical representation
of the message's meaning:

```python
[0.023, -0.412, 0.871, 0.003, ..., 0.124]  # 1024 numbers
```

**If Jina fails (451, timeout, rate limit):**
- `EmbeddingError` raised → caught in `RetrieverService`
- Returns empty list `[]`
- `log WARNING FALLBACK | embedding failed`
- Evaluation will see `max_similarity=0.0 < 0.45` → `needs_human=True`

### Step 2 — Similarity search in pgvector (local DB, no internet)

```sql
SELECT content, source_file, chunk_index,
       1 - (embedding <=> '[0.023, -0.412, ...]'::vector) AS similarity
FROM knowledge_chunks
ORDER BY embedding <=> '[0.023, -0.412, ...]'::vector
LIMIT 4;
```

The `<=>` operator is pgvector's **cosine distance**.
pgvector uses the `ivfflat` index (approximate nearest neighbor, fast)
to find the 4 chunks whose stored 1024-dim vectors are closest to the query vector.

`similarity = 1 - cosine_distance` → higher means more relevant.

**Result:**
```
vip_products.txt §0    similarity=0.82  ← most relevant
vip_products.txt §1    similarity=0.76
exchange_signup.txt §2 similarity=0.65
rastad_services.txt §0 similarity=0.61
```

Logged:
```
[INFO] RETRIEVE | chunks=4 top_similarity=0.82 latency_ms=290
[INFO] CHUNK[1] | vip_products.txt §0 similarity=0.8200 | اشتراک VIP راستاد دسترسی به سیگنال‌های اختصاصی...
[INFO] CHUNK[2] | vip_products.txt §1 similarity=0.7600 | خدمات اشتراک VIP شامل موارد زیر است...
[INFO] CHUNK[3] | exchange_signup.txt §2 similarity=0.6500 | برای ثبت‌نام در صرافی...
[INFO] CHUNK[4] | rastad_services.txt §0 similarity=0.6100 | راستاد یک پلتفرم تخصصی...
```

---

## Phase 2d — Evaluation (pure logic, no API calls)

`EvaluatorService.evaluate(chunks, classification)` — runs three independent checks:

```python
max_similarity = 0.82

low_confidence = 0.82 < 0.45          # → False
is_support     = "vip_question" == "support_request"  # → False
llm_flagged    = False                 # from ClassificationResult

reasons = []  # empty → needs_human = False
```

Confidence label: `0.82 >= 0.7` → `"HIGH"`

**All three signals false → needs_human_support = False.**

Logged:
```
[INFO] EVALUATE | needs_human=False confidence=HIGH   similarity=0.82 threshold=0.45 reason=none
```

**When needs_human becomes True — the three triggers:**

| Trigger | Condition | Reason logged |
|---|---|---|
| Low KB confidence | `max_similarity < 0.45` | `low_confidence` |
| Support intent | `intent == "support_request"` | `support_request_intent` |
| LLM flagged | `classification.needs_human_support == True` | `llm_flagged` |
| Multiple | any combination | `low_confidence,llm_flagged` etc. |

---

## Phase 2e — Generation — LLM call #2 (goes to internet)

`GeneratorService.generate(message, chunks, intent="vip_question", needs_human=False)`

### Why a second LLM call

The first call (classify) returned structured data — intent/segment/needs_human.
This second call generates the actual Persian reply text, grounded in the KB chunks.
These are two separate jobs with different prompts.

The top 3 chunk texts are injected into the generation prompt:

```
SYSTEM: تو دستیار هوشمند پشتیبانی راستاد هستی...

--- اطلاعات راستاد ---
اشتراک VIP راستاد دسترسی به سیگنال‌های اختصاصی اسپات و فیوچرز...

خدمات اشتراک VIP شامل سیگنال‌های معاملاتی اسپات و فیوچرز...

برای مشاهده پلن‌های اشتراک به smrastad.com/vip مراجعه کنید.
----------------------

نوع درخواست: vip_question
USER: خدمات VIP راستاد چیه؟
```

**HTTP POST sent to OpenRouter** (same endpoint, same key, same model).

**Raw reply after `_strip_thinking()`:**
```
اشتراک VIP راستاد دسترسی به سیگنال‌های اختصاصی اسپات و فیوچرز،
تحلیل‌های تکنیکال و فاندامنتال و پشتیبانی ویژه را فراهم می‌کند.
برای خرید به smrastad.com/vip مراجعه کنید.
```

**If needs_human=True and no chunks exist:**
- Skip LLM call entirely (`latency_ms=0` in logs)
- Return the hardcoded Persian handoff template directly
- `fallback_used=False` (template is not a fallback, it's intentional)

**If LLM generate call fails:**
- Use first chunk's content as reply
- `fallback_used=True`

Logged:
```
[INFO] GENERATE | provider=openrouter  model=qwen/qwen3-8b  fallback=False latency_ms=930
```

---

## Timing snapshot

```
t0       → pipeline starts
t_user   → user created/fetched          other_ms contribution: ~2ms
t_classify → LLM classify done           llm_ms contribution:   820ms
t_retrieve → Jina + pgvector done        embedding_ms:          290ms
t_evaluate → evaluation done             other_ms contribution: ~3ms
t_generate → LLM generate done           llm_ms contribution:   930ms

llm_ms       = 820 + 930  = 1750ms
embedding_ms =              290ms
other_ms     = 2 + 3      =   5ms
total_ms     =             2045ms
```

---

## Phase 2f — Persist to database

Two writes, wrapped in `try/except` — a DB failure never blocks the response.

**Write 1 — save message:**
```sql
INSERT INTO messages
  (user_id, user_message, assistant_reply, intent, needs_human_support, created_at)
VALUES (3, 'خدمات VIP...', 'اشتراک VIP راستاد...', 'vip_question', false, now());
```

**Write 2 — update user segment:**
```sql
UPDATE rastad_users
SET segment='vip_interest', last_seen_at=now()
WHERE user_id=3;
```

---

## Phase 3 — Response returned

```
[INFO] DONE | llm_ms=1750 embedding_ms=290 other_ms=5 total_ms=2045
```

HTTP 200 with JSON body:

```json
{
  "reply": "اشتراک VIP راستاد دسترسی به سیگنال‌های اختصاصی...",
  "intent": "vip_question",
  "user_segment": "vip_interest",
  "needs_human_support": false,
  "confidence": 0.82,
  "chunks_used": [
    "vip_products.txt §0",
    "vip_products.txt §1",
    "exchange_signup.txt §2",
    "rastad_services.txt §0"
  ],
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

---

## Complete timeline

```
0ms      HTTP arrives, middleware runs
1ms      Serializer validates input
3ms      UserRepository creates/fetches user
823ms    LLM call #1 done — ClassificationResult validated
1113ms   Jina embeds query (internet) + pgvector finds top-4 (local DB)
1116ms   EvaluatorService runs (pure Python, < 1ms)
2046ms   LLM call #2 done — grounded Persian reply generated
2047ms   Structured payload logged at DEBUG
2048ms   2 DB writes committed
2050ms   HTTP 200 response sent to caller
```

---

## What happens when each part fails

```
┌─────────────────────┬──────────────────────────────────┬─────────────────────────────┐
│ Failure             │ What runs instead                │ User sees                   │
├─────────────────────┼──────────────────────────────────┼─────────────────────────────┤
│ LLM classify fails  │ RuleBasedClassifier (keywords)   │ Reply, needs_human=True     │
│ JSON invalid x2     │ RuleBasedClassifier              │ Reply, needs_human=True     │
│ Jina embed fails    │ chunks=[], skip pgvector         │ Handoff template            │
│ similarity < 0.45   │ EvaluatorService flags it        │ Handoff template            │
│ LLM generate fails  │ Best chunk text as reply         │ Chunk text, fallback=True   │
│ DB write fails      │ Error logged silently            │ Full reply still returned   │
└─────────────────────┴──────────────────────────────────┴─────────────────────────────┘
```

In every failure path: the user always gets a response, the system never crashes,
every failure is logged with its reason.

---

## Internet calls per request — summary

| Call | Provider | When | Can be skipped |
|---|---|---|---|
| Classification | OpenRouter (Qwen3-8b) | Always | If `LLM_PROVIDER=mock` |
| Embedding | Jina AI | Always | If `EMBEDDING_PROVIDER=mock` |
| Generation | OpenRouter (Qwen3-8b) | Always except handoff | If `LLM_PROVIDER=mock` |

Maximum 3 external API calls per request (classify + embed + generate).
Minimum 0 if running in mock mode (tests, offline dev).
