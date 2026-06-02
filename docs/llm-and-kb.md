# LLM, Embeddings & Knowledge Base — Design

## 1. Providers

LLM and embeddings use separate providers — one for language, one for vectors.

| Purpose | Provider | Model | Key |
|---|---|---|---|
| Classification + Reply generation | OpenRouter (default) | `qwen/qwen3-8b` | `LLM_API_KEY` |
| Classification + Reply generation | OpenAI (optional) | `gpt-4o-mini` | `OPENAI_API_KEY` |
| Embeddings | Jina AI | `jina-embeddings-v3` | `JINA_API_KEY` |

### Why separate providers for LLM and embeddings
OpenRouter does not expose an embeddings endpoint — it routes chat completions only.
Jina AI was chosen for embeddings: free hosted tier, strong multilingual/Persian support,
simple REST API, 1024-dimension output.

### Switching LLM provider — `.env` only, zero code changes

```env
# OpenRouter (default)
LLM_PROVIDER=openrouter
LLM_API_KEY=sk-or-v1-...
LLM_MODEL=qwen/qwen3-8b

# OpenAI
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
LLM_MODEL=gpt-4o-mini

# Mock (tests, offline)
LLM_PROVIDER=mock
```

`adapters/factory.py` reads `LLM_PROVIDER` at startup and returns the correct adapter.
No service layer code changes for any provider switch.

---

## 2. Port Interfaces

All service layer code depends on these interfaces only — never on a concrete adapter.

```python
# core/ports.py

from typing import Protocol

class LLMPort(Protocol):
    def classify(self, message: str) -> ClassificationResult: ...
    def generate_reply(self, message: str, chunks: list[str], intent: str) -> str: ...

class EmbeddingPort(Protocol):
    def embed(self, text: str, task: str = "retrieval.query") -> list[float]: ...
```

Note: `EmbeddingPort.embed` takes a `task` parameter — Jina AI requires different task
values for indexing (`retrieval.passage`) vs querying (`retrieval.query`).

Concrete implementations:
- `adapters/llm/openrouter.py` — OpenRouter chat completions
- `adapters/llm/openai.py` — OpenAI chat completions
- `adapters/llm/mock.py` — deterministic keyword-based (tests + offline)
- `adapters/embedding/jina.py` — Jina AI embeddings (dim 1024)
- `adapters/embedding/mock.py` — zero-vector stub (tests)

---

## 3. Pydantic Output Validation + Retry Loop

Classification returns a strictly typed result. If the LLM output is invalid,
the system retries with the error reason injected back into the prompt.
This is the core reliability mechanism — no silent wrong classifications.

```python
# core/types.py

from pydantic import BaseModel
from typing import Literal

class ClassificationResult(BaseModel):
    intent: Literal[
        "vip_question",
        "exchange_registration",
        "kol_collaboration",
        "support_request",
        "general_info",
        "unknown"
    ]
    segment: Literal[
        "new_user",
        "vip_interest",
        "exchange_signup",
        "kol_candidate",
        "support_needed",
        "general_question"
    ]
    needs_human_support: bool
```

### Retry flow

```
LLM returns raw string
    → _strip_thinking(): remove <think>…</think> blocks (Qwen3 extended thinking)
    → json.loads() → dict
    → ClassificationResult(**dict)  [Pydantic validation]
    → SUCCESS: return ClassificationResult

    → ValidationError / JSONDecodeError:
        → retry 1: rebuild prompt with error reason injected
        → retry 2: rebuild prompt with stricter instruction
        → still fails: RuleBasedClassifier.classify(message)
                       needs_human_support = True
                       log WARNING FALLBACK
```

### Qwen3 thinking block stripping
Qwen3-8b outputs `<think>…</think>` reasoning blocks before its actual answer.
These are stripped from both classification output (before JSON parsing) and
generation output (before returning the reply to the user).

```python
def _strip_thinking(text: str) -> str:
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
```

### Error injection prompt (Persian, matches user language)

```
خطای قبلی: {validation_error}
مقادیر مجاز برای intent: vip_question, exchange_registration, ...
مقادیر مجاز برای segment: new_user, vip_interest, ...
فقط یک JSON معتبر برگردان. هیچ متن اضافه‌ای نداشته باش.
```

Max retries: **2**. After that → rule-based fallback, no more LLM calls.

---

## 4. Classification Prompt Design

One call returns all three fields: `intent`, `segment`, `needs_human_support`.
Sent with `temperature=0.3` for consistent structured output.

```
SYSTEM:
تو یک سیستم دسته‌بندی هوشمند برای پشتیبانی کاربران راستاد هستی.
راستاد یک پلتفرم تخصصی ارز دیجیتال با بیش از ۵۴۴ هزار دنبال‌کننده است که خدمات سیگنال، تحلیل، اشتراک VIP، برنامه KOL و معرفی صرافی ارائه می‌دهد.
پیام کاربر را تحلیل کن و دقیقاً یک JSON با این ساختار برگردان:

{
  "intent": "<یکی از مقادیر مجاز>",
  "segment": "<یکی از مقادیر مجاز>",
  "needs_human_support": <true یا false>
}
...
فقط JSON برگردان. بدون توضیح اضافه.

USER:
{message}
```

---

## 5. Reply Generation Prompt Design

KB chunks are injected as context. The reply must be grounded in them.
An extra instruction was added to prevent thinking/analysis leaking into the reply.

```
SYSTEM:
تو دستیار هوشمند پشتیبانی راستاد هستی.
...
- هیچ توضیح یا تحلیل اضافه‌ای ننویس، فقط پاسخ نهایی

--- اطلاعات راستاد ---
{chunk_1}

{chunk_2}

{chunk_3}
----------------------

نوع درخواست: {intent}

USER:
{message}
```

If no chunks are above the confidence threshold, the reply template is used:
```
"متأسفم، در حال حاضر اطلاعات کافی برای پاسخ به این سوال ندارم.
تیم پشتیبانی راستاد در اسرع وقت با شما تماس می‌گیرد."
```
And `needs_human_support` is forced to `True` by `EvaluatorService`.

---

## 6. Mock Adapter

Used when `LLM_PROVIDER=mock` in `.env`. No API calls, fully deterministic.
Based on keyword matching — used by tests and for running without API keys.

Keywords matched: `vip`, `صرافی`, `kol`, `مشکل`, `پرداخت`, `همکاری`, `ثبت`, `اشتراک`

The mock embedding adapter (`adapters/embedding/mock.py`) returns a zero vector
of dimension `settings.EMBEDDING_DIM` — no network call, no Jina key needed.

---

## 7. Knowledge Base — File Structure

Directory: `knowledge_base/`

Each file is plain Persian text, organized in short focused paragraphs.
One topic per paragraph. Paragraphs separated by blank lines (`\n\n`).

```
knowledge_base/
├── rastad_services.txt     # General overview of Rastad platform
├── vip_products.txt        # VIP tiers, features, pricing, upgrade process
├── exchange_signup.txt     # Exchange registration steps, requirements, KYC
└── kol_program.txt         # KOL collaboration, requirements, benefits
```

---

## 8. Chunking Strategy

### Algorithm
```
read file content
    → strip leading/trailing whitespace
    → split on "\n\n"  (paragraph separator)
    → filter: remove chunks shorter than 20 characters
    → assign: chunk_index = 0, 1, 2, ...
    → compute: content_hash = md5(content)
```

### Idempotent indexing
```python
existing = KnowledgeChunk.objects.filter(
    source_file=filename, chunk_index=chunk_index
).first()
if existing and existing.content_hash == content_hash:
    continue          # unchanged — skip embedding API call
embedding = embedder.embed(content, task="retrieval.passage")
KnowledgeChunk.objects.update_or_create(...)
```

`python manage.py index_knowledge_base` is safe to run anytime.
Only changed or new chunks hit the Jina API.

### pgvector column
```sql
embedding vector(1024)   -- Jina jina-embeddings-v3 output dimension
```

Dimension is read from `settings.EMBEDDING_DIM` (default `1024`).

Similarity query at request time:
```sql
SELECT content, source_file, chunk_index,
       1 - (embedding <=> %s::vector) AS similarity
FROM knowledge_chunks
ORDER BY embedding <=> %s::vector
LIMIT 4;
```

`1 - cosine_distance = cosine_similarity` — higher is more relevant.
EvaluatorService checks: `max(similarity) < 0.45` → low confidence → human handoff.
