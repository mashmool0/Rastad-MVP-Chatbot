# LLM, Embeddings & Knowledge Base — Design

## 1. Provider

All LLM and embedding calls go through **OpenRouter** — one API key, one provider.

| Purpose | Model |
|---|---|
| Classification + Reply generation | `qwen/qwen3-8b` |
| Embeddings | `qwen/qwen3-8b` (or OpenRouter embedding endpoint — confirmed at implementation) |

Base URL: `https://openrouter.ai/api/v1`
Auth: `Authorization: Bearer $OPENROUTER_API_KEY`

Why Qwen3-8b: best free multilingual model on OpenRouter, strong Persian language
quality, handles structured JSON output reliably.

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
    def embed(self, text: str) -> list[float]: ...
```

Concrete implementations:
- `adapters/llm/openrouter.py` — real OpenRouter calls
- `adapters/llm/mock.py` — deterministic mock (keyword-based, for tests + offline)
- `adapters/embedding/openrouter.py` — real embedding calls

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

مقادیر مجاز برای intent:
- vip_question: سوال درباره خدمات VIP
- exchange_registration: ثبت‌نام یا سوال درباره صرافی
- kol_collaboration: همکاری به عنوان KOL
- support_request: مشکل فنی، پرداخت، یا نیاز به پشتیبانی
- general_info: سوال اطلاعاتی عمومی
- unknown: پیام نامفهوم یا خارج از موضوع

مقادیر مجاز برای segment:
- new_user: کاربر جدید بدون سابقه
- vip_interest: علاقه‌مند به خدمات VIP
- exchange_signup: در حال ثبت‌نام در صرافی
- kol_candidate: داوطلب همکاری KOL
- support_needed: نیاز به پشتیبانی فوری
- general_question: سوال عمومی

needs_human_support = true اگر:
- مشکل پرداخت یا فنی گزارش شده
- پیام عصبانی یا اضطراری است
- موضوع خارج از دانش سیستم است

فقط JSON برگردان. بدون توضیح اضافه.

USER:
{message}
```

---

## 5. Reply Generation Prompt Design

KB chunks are injected as context. The reply must be grounded in them.

```
SYSTEM:
تو دستیار هوشمند پشتیبانی راستاد هستی.
راستاد یک پلتفرم تخصصی ارز دیجیتال است با کانال تلگرام @RastadCo (۵۴۴ هزار عضو)، اشتراک VIP، خدمات Trade Assist، برنامه KOL و معرفی صرافی.
سایت رسمی: smrastad.com | پشتیبانی: @Rastad_support | ربات: @Rastad_bot
بر اساس اطلاعات زیر به کاربر پاسخ بده.
پاسخ باید:
- فارسی و محترمانه باشد
- فقط از اطلاعات داده‌شده استفاده کند
- کوتاه و مستقیم باشد (حداکثر ۳ جمله)
- اگر اطلاعات کافی نداری، بگو تیم پشتیبانی کمک می‌کند

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
Based on keyword matching — useful for tests and running without an API key.

```python
# adapters/llm/mock.py

MOCK_CLASSIFICATIONS = {
    "vip":        ClassificationResult(intent="vip_question",        segment="vip_interest",    needs_human_support=False),
    "صرافی":      ClassificationResult(intent="exchange_registration",segment="exchange_signup", needs_human_support=False),
    "kol":        ClassificationResult(intent="kol_collaboration",    segment="kol_candidate",   needs_human_support=False),
    "مشکل":       ClassificationResult(intent="support_request",      segment="support_needed",  needs_human_support=True),
    "پرداخت":     ClassificationResult(intent="support_request",      segment="support_needed",  needs_human_support=True),
}
# default → general_info / general_question / False

MOCK_REPLIES = {
    "vip_question":         "خدمات VIP راستاد شامل تحلیل‌های اختصاصی و مدیر اکانت است.",
    "exchange_registration":"برای ثبت‌نام در صرافی به بخش ثبت‌نام مراجعه کنید.",
    "kol_collaboration":    "برنامه KOL راستاد برای اینفلوئنسرها مزایای ویژه دارد.",
    "support_request":      "تیم پشتیبانی راستاد در اسرع وقت با شما تماس می‌گیرد.",
    "general_info":         "راستاد یک پلتفرم جامع برای معامله‌گران ارز دیجیتال است.",
}
```

The mock is also what endpoint tests run against — fast, no network, no cost.

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

### File format convention

```
# [عنوان موضوع]

[پاراگراف ۱ — یک موضوع مشخص، ۲ تا ۴ جمله]

[پاراگراف ۲ — موضوع مرتبط بعدی]

[پاراگراف ۳ — ...]
```

Example (`vip_products.txt`):
```
# خدمات VIP راستاد

خدمات VIP راستاد در سه سطح Bronze، Silver و Gold ارائه می‌شود.
هر سطح دسترسی به تحلیل‌های اختصاصی، سیگنال‌های معاملاتی و پشتیبانی ویژه دارد.

سطح Gold شامل مدیر اکانت اختصاصی، وبینارهای خصوصی و اولویت در پشتیبانی است.
این سطح برای معامله‌گران حرفه‌ای و حجم معاملات بالا طراحی شده.

برای ارتقا به VIP کافی است از پنل کاربری درخواست ارتقا ثبت کنید.
تیم راستاد ظرف ۲۴ ساعت بررسی و تأیید می‌کند.
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

No sliding window, no fixed token size. Paragraph boundaries are natural
semantic boundaries for this type of content — each chunk has one clear meaning.

### Chunk size expectations
- Min: ~20 chars (filtered out if shorter)
- Typical: 100–400 chars (2–5 sentences)
- Max: no hard limit, but KB files should be authored to keep paragraphs short

### Idempotent indexing
```python
for chunk in chunks:
    existing = KnowledgeChunk.objects.filter(
        source_file=filename, chunk_index=chunk.index
    ).first()
    if existing and existing.content_hash == chunk.hash:
        continue          # unchanged — skip embedding API call
    embedding = EmbeddingAdapter.embed(chunk.content)
    KnowledgeChunk.objects.update_or_create(...)
```

This means `python manage.py index_knowledge_base` is safe to run anytime.
Only changed or new chunks hit the embedding API.

### pgvector column
```sql
embedding vector(1536)   -- dimension matches the OpenRouter embedding model output
```

Similarity query at request time:
```sql
SELECT content, source_file,
       1 - (embedding <=> %s::vector) AS similarity
FROM knowledge_chunks
ORDER BY embedding <=> %s::vector
LIMIT 4;
```

The `%s` parameter is the embedded user message vector.
`1 - cosine_distance = cosine_similarity` — higher is more relevant.
EvaluatorService checks: `max(similarity) < 0.45` → low confidence → human handoff.
