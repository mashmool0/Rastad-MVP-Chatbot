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
- Built-in auth (`django.contrib.auth`) covers our login/signup requirement with zero extra work
- DRF serializers give free input validation — a scored criterion
- ORM + migrations handle the multi-model schema (User, Message, KnowledgeChunk + pgvector) cleanly
- Faster implementation time when the developer knows Django well

**Trade-off accepted:**
For a high-concurrency async service, FastAPI would be the right choice.
Django's sync ORM becomes a bottleneck at scale. Acknowledged in README limitations.

---

## 2. PostgreSQL + pgvector over a Separate Vector DB

**Context:** The task awards bonus points for using a vector DB (FAISS, Chroma, Qdrant).

**Options:**
- Qdrant — purpose-built vector DB, runs as a separate container, excellent performance
- Chroma — easiest to embed in-process, minimal setup
- FAISS — in-memory, no persistence without extra work
- pgvector — PostgreSQL extension, same DB we already have

**Decision:** pgvector inside PostgreSQL

**Why:**
- Zero additional infrastructure — one DB, one Docker service, one connection string
- Operational simplicity: no second container to manage, no second backup strategy
- Django ORM integration via `django-pgvector` — models, migrations, queries all stay in Django
- Strong interview story: "I kept the vector store in Postgres to reduce operational surface area"
- For MVP scale (4 KB files, <100 chunks), performance is identical to Qdrant

**Trade-off accepted:**
At large scale (millions of vectors), a dedicated vector DB like Qdrant outperforms pgvector.
For this MVP, the scale doesn't justify the added complexity.

---

## 3. One LLM Call for Classification (Not Two)

**Context:** We need intent, segment, and needs_human_support for every message.

**Options:**
- One call returning all three fields as JSON
- Two calls: classify intent+segment first, then decide needs_human separately

**Decision:** One call, structured JSON output, Pydantic-validated

**Why:**
- Halves LLM API calls per request — lower latency, lower cost
- The model can reason about all three together (intent informs segment informs needs_human)
- Pydantic validation with retry handles the reliability concern
- The EvaluatorService then adds KB-confidence as a second signal on top — LLM output is one input, not the final word

**Trade-off accepted:**
A single prompt asking for three things is slightly harder to tune than three focused prompts.
Mitigated by clear enum constraints in the prompt and retry logic.

---

## 4. Pydantic Validation + Retry over Silent Fallback

**Context:** LLMs don't always return valid structured JSON on the first try.

**Options:**
- Accept whatever the LLM returns, fail silently if invalid
- Parse best-effort with regex
- Validate with Pydantic, retry with error feedback injected into prompt, fallback to rules

**Decision:** Pydantic + retry (max 2) + rule-based fallback

**Why:**
- Silent failures produce wrong intent/segment stored in DB — corrupts analytics
- Regex parsing is brittle for Persian text and nested JSON
- Retry with error feedback works well with instruction-following models (Qwen3-8b)
- Rule-based fallback guarantees the system always returns a valid ClassificationResult
- The retry error message is in Persian, matching the user's language and the model's tuning

**Trade-off accepted:**
Up to 2 extra LLM calls in the failure path. Rare in practice with a well-prompted model.
Max total classification calls: 3. Still completes in well under 5 seconds.

---

## 5. Rule-Based Fallback When LLM Fails

**Context:** The interview explicitly asks: "What does the system do if the LLM goes down?"

**Options:**
- Return an error to the user
- Queue the message for retry
- Fall back to deterministic keyword classifier

**Decision:** Keyword-based `RuleBasedClassifier` as synchronous fallback

**Why:**
- System stays up and responds — user never sees a 500 error because OpenRouter is down
- Keywords for Persian crypto/trading vocabulary are well-defined (vip, صرافی, kol, مشکل, پرداخت...)
- `needs_human_support = True` on all fallback responses — honest about reduced confidence
- Zero latency, zero cost, zero external dependency

**Trade-off accepted:**
Keyword matching is less accurate than LLM classification.
Fallback is clearly logged (`WARNING FALLBACK`) so operators can monitor fallback frequency.

---

## 6. Confidence Threshold for needs_human_support

**Context:** We need a reliable signal for when a human agent should take over.

**Options:**
- Trust only the LLM's own `needs_human_support` field
- Always derive from intent (support_request → true, rest → false)
- Combine: LLM signal + KB similarity confidence + intent rule

**Decision:** Three-signal combination in EvaluatorService

```
needs_human_support = True  if:
    max(chunk similarity) < 0.45   (KB can't answer this — no relevant knowledge)
    OR intent == "support_request"  (user explicitly has a problem)
    OR llm.needs_human == True      (LLM itself flagged it)
```

**Why:**
- A question the KB can't answer confidently should go to a human, even if the LLM tries to answer
- Combining three independent signals reduces both false positives and false negatives
- The threshold (0.45) is configurable via `CONFIDENCE_THRESHOLD` env var — tuneable without code changes

**Trade-off accepted:**
Threshold requires empirical tuning per real knowledge base content.
0.45 is a reasonable starting point for cosine similarity with sentence-transformer embeddings.

---

## 7. Paragraph Chunking over Fixed-Token Sliding Window

**Context:** KB files need to be split into chunks for pgvector indexing.

**Options:**
- Fixed token size (e.g. 256 tokens) with overlap
- Sentence-level splitting
- Paragraph splitting (double newline)
- Semantic chunking (LLM-assisted)

**Decision:** Paragraph splitting on `\n\n`

**Why:**
- KB files are short (4 files, ~10 paragraphs each) and author-controlled
- Each paragraph covers one atomic topic — preserves semantic coherence
- No overlap needed: paragraphs don't split mid-thought
- Simplest implementation, easiest to debug, easiest to explain
- Content hash per chunk enables idempotent re-indexing

**Trade-off accepted:**
Paragraph size is inconsistent — some chunks may be longer than others.
Fine for this scale. At production scale with large documents, fixed-token + overlap is better.

---

## 8. One Provider (OpenRouter) for LLM + Embeddings

**Context:** We need both a chat LLM and an embedding model.

**Options:**
- OpenRouter for LLM + HuggingFace Inference API for embeddings (two providers)
- OpenRouter for both (one provider, one API key)
- Local sentence-transformers for embeddings + OpenRouter for LLM

**Decision:** OpenRouter for both

**Why:**
- One API key in `.env` — simpler configuration, simpler secrets management
- One provider to monitor, one billing account, one rate limit to reason about
- Swapping to a different provider later changes one adapter file, not two

**Trade-off accepted:**
OpenRouter's embedding support should be verified at implementation time.
If unavailable, fall back to local `sentence-transformers` — zero cost, runs in Docker,
no API dependency. The adapter interface isolates this change from all other code.

---

## 9. Django Built-in Auth for UI Login

**Context:** The UI at `/` requires login. We added `/login` and `/signup`.

**Options:**
- JWT-based custom auth
- Django sessions + built-in `django.contrib.auth`
- Third-party (OAuth, Allauth)

**Decision:** Django sessions + built-in auth

**Why:**
- Ships with Django — zero extra dependencies
- `@login_required` decorator handles route protection in one line
- Password hashing (PBKDF2) built-in — no security mistakes possible here
- `signup` view creates both `auth.User` and `RastadUser` in one transaction (1:1 linked)

**Auth ↔ RastadUser link:**
When a user signs up, a `RastadUser` is created with an auto-incremented integer `user_id`
linked to their `auth.User` via `OneToOneField`. Login session → know the `user_id` →
UI fills it automatically → messages tied to account → users comparable in admin panel.

**Trade-off accepted:**
Session auth doesn't scale to stateless multi-instance deployments.
Acknowledged: this is a single-instance MVP. JWT would be the path forward.
