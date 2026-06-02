# Data Model — Rastad AI Assistant

## 1. Entity Relationship Diagram

```
┌─────────────────────┐          ┌──────────────────────────┐
│   auth.User          │          │      RastadUser           │
│─────────────────────│  0/1 : 1 │──────────────────────────│
│ id (AutoField PK)   │◄────────►│ user_id (AutoField PK)    │
│ username            │          │ auth_user (OneToOne, null) │
│ password (hashed)   │          │ name (CharField)          │
│ date_joined         │          │ segment (CharField)       │
│ ...                 │          │ created_at (DateTimeField)│
└─────────────────────┘          │ last_seen_at (DateTimeField)│
                                  └────────────┬─────────────┘
                                               │ 1
                                               │
                                               │ ∞
                                  ┌────────────▼─────────────┐
                                  │         Message           │
                                  │──────────────────────────│
                                  │ id (AutoField PK)         │
                                  │ user (FK → RastadUser)    │
                                  │ user_message (TextField)  │
                                  │ assistant_reply (TextField)│
                                  │ intent (CharField)        │
                                  │ needs_human_support (Bool)│
                                  │ created_at (DateTimeField)│
                                  └──────────────────────────┘

┌──────────────────────────────────┐
│         KnowledgeChunk            │
│──────────────────────────────────│
│ id (AutoField PK)                 │
│ source_file (CharField)           │
│ chunk_index (IntegerField)        │
│ content (TextField)               │
│ content_hash (CharField, MD5)     │
│ embedding (VectorField dim=1024)  │
└──────────────────────────────────┘
```

KnowledgeChunk has no FK to other models — it is a standalone index of KB content.

**Note on `auth_user`:** The field is nullable (`null=True, blank=True`).
The open API (`POST /api/message`) creates `RastadUser` records without a Django auth
account — `auth_user` is `None` for API-created users. The signup flow (UI, 2nd pass)
links a `auth.User` after the fact. This differs from the original spec which required
a non-null `OneToOneField`.

---

## 2. Model Definitions

### auth.User
Django's built-in model — not redefined. Used as-is.
Login/signup creates and authenticates these records.

---

### RastadUser

```python
# apps/users/models.py

from django.contrib.auth import get_user_model
from django.db import models

User = get_user_model()

SEGMENT_CHOICES = [
    ("new_user",         "New User"),
    ("vip_interest",     "VIP Interest"),
    ("exchange_signup",  "Exchange Signup"),
    ("kol_candidate",    "KOL Candidate"),
    ("support_needed",   "Support Needed"),
    ("general_question", "General Question"),
]

class RastadUser(models.Model):
    user_id      = models.AutoField(primary_key=True)
    auth_user    = models.OneToOneField(
        User, on_delete=models.CASCADE,
        related_name="rastad_profile",
        null=True, blank=True,           # nullable — API users have no auth account
    )
    name         = models.CharField(max_length=255)
    segment      = models.CharField(max_length=50, choices=SEGMENT_CHOICES, default="new_user")
    created_at   = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "rastad_users"

    def __str__(self):
        return f"{self.name} (#{self.user_id})"
```

---

### Message

```python
# apps/messages/models.py

from django.db import models
from apps.users.models import RastadUser

INTENT_CHOICES = [
    ("vip_question",          "VIP Question"),
    ("exchange_registration",  "Exchange Registration"),
    ("kol_collaboration",      "KOL Collaboration"),
    ("support_request",        "Support Request"),
    ("general_info",           "General Info"),
    ("unknown",                "Unknown"),
]

class Message(models.Model):
    user                = models.ForeignKey(RastadUser, on_delete=models.CASCADE, related_name="messages")
    user_message        = models.TextField()
    assistant_reply     = models.TextField()
    intent              = models.CharField(max_length=50, choices=INTENT_CHOICES)
    needs_human_support = models.BooleanField(default=False)
    created_at          = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "messages"
        ordering = ["-created_at"]
        indexes  = [
            models.Index(fields=["user"], name="idx_message_user"),
        ]
```

**Django app label:** `apps.messages` conflicts with Django's built-in `django.contrib.messages`.
The app config sets `label = "rastad_messages"` to resolve this. Migrations live under
`apps/messages/migrations/` but use `app_label = "rastad_messages"` internally.

---

### KnowledgeChunk

```python
# apps/knowledge/models.py

from django.conf import settings
from django.db import models
from pgvector.django import VectorField

class KnowledgeChunk(models.Model):
    source_file  = models.CharField(max_length=255)
    chunk_index  = models.IntegerField()
    content      = models.TextField()
    content_hash = models.CharField(max_length=32)
    embedding    = VectorField(dimensions=settings.EMBEDDING_DIM)  # 1024

    class Meta:
        db_table        = "knowledge_chunks"
        unique_together = [("source_file", "chunk_index")]
        indexes = [
            models.Index(fields=["source_file", "chunk_index"], name="idx_chunk_lookup"),
        ]
```

`EMBEDDING_DIM=1024` matches `jina-embeddings-v3` output. Configured via `.env` and
read from `settings.EMBEDDING_DIM` — not hardcoded.

---

## 3. Field Type Decisions

| Field | Type | Reason |
|---|---|---|
| `user_id` | AutoField (int PK) | Simple 1,2,3 IDs, DB-assigned, no collision risk |
| `auth_user` | OneToOneField (nullable) | Optional link — API users exist without a login account |
| `segment` | CharField with choices | Validated at app level via DRF serializer |
| `last_seen_at` | DateTimeField(auto_now=True) | Updated on every save — no manual tracking |
| `user_message` | TextField | No length limit — user messages can be long |
| `intent` | CharField with choices | Limited enum — choices enforce data quality |
| `needs_human_support` | BooleanField | Not null, always set by EvaluatorService |
| `content_hash` | CharField(32) | MD5 hex — used to skip re-embedding unchanged chunks |
| `embedding` | VectorField(1024) | Dimension matches Jina `jina-embeddings-v3` output |

---

## 4. Indexes

| Table | Index | Type | Purpose |
|---|---|---|---|
| `messages` | `user_id` | BTree | `GET /users/{id}/messages` filter |
| `knowledge_chunks` | `(source_file, chunk_index)` | BTree | Idempotent upsert lookup |
| `knowledge_chunks` | `embedding` | ivfflat | Fast approximate vector similarity search |
| `rastad_users` | `auth_user_id` | BTree (auto) | OneToOneField — Django creates this automatically |

---

## 5. Migration Setup — pgvector

pgvector requires the PostgreSQL extension to be enabled before the first migration
that uses `VectorField`. Three migrations in `apps/knowledge/migrations/`:

### 0001 — enable pgvector extension (hand-written)
```python
migrations.RunSQL("CREATE EXTENSION IF NOT EXISTS vector;")
```

### 0002 — create KnowledgeChunk table (auto-generated by makemigrations)
Depends on `0001_enable_pgvector`.

### 0003 — add ivfflat index (hand-written)
```python
migrations.RunSQL("""
    CREATE INDEX IF NOT EXISTS idx_chunk_embedding_ivfflat
    ON knowledge_chunks
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 10);
""")
```

`lists = 10` is appropriate for < 1000 vectors. Formula: `lists ≈ rows / 100`.

---

## 6. API-created User Flow

When `POST /api/message` is called without a matching `user_id`, a `RastadUser`
is created with `auth_user=None`. The DB assigns the `user_id` automatically.

```python
# UserRepository.get_or_create
if user_id:
    user, _ = RastadUser.objects.get_or_create(user_id=user_id, defaults={"name": name})
else:
    user = RastadUser.objects.create(name=name)  # auth_user stays None
```

---

## 7. Database Configuration (docker-compose)

```yaml
db:
  image: pgvector/pgvector:pg16   # official image with pgvector pre-installed
  environment:
    POSTGRES_DB: ${DB_NAME}
    POSTGRES_USER: ${DB_USER}
    POSTGRES_PASSWORD: ${DB_PASSWORD}
  ports:
    - "5433:5432"                 # 5433 on host to avoid clash with local Postgres
  volumes:
    - postgres_data:/var/lib/postgresql/data
```

Port `5433` on the host is intentional — local PostgreSQL installations typically
occupy `5432`. The app container connects via internal Docker network on `db:5432`.
Local `manage.py` commands connect via `localhost:5433` (set `DB_PORT=5433` in `.env`).
