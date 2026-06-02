# Data Model — Rastad AI Assistant

## 1. Entity Relationship Diagram

```
┌─────────────────────┐          ┌──────────────────────────┐
│   auth.User          │          │      RastadUser           │
│─────────────────────│  1 : 1   │──────────────────────────│
│ id (AutoField PK)   │◄────────►│ user_id (IntegerField PK) │
│ username            │          │ auth_user (OneToOneField) │
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
│ embedding (VectorField dim=1536)  │
└──────────────────────────────────┘
```

KnowledgeChunk has no FK to other models — it is a standalone index of KB content.

---

## 2. Model Definitions

### auth.User
Django's built-in model — not redefined. Used as-is.
Login/signup creates and authenticates these records.

---

### RastadUser

```python
# apps/users/models.py

from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()

SEGMENT_CHOICES = [
    ("new_user",        "New User"),
    ("vip_interest",    "VIP Interest"),
    ("exchange_signup", "Exchange Signup"),
    ("kol_candidate",   "KOL Candidate"),
    ("support_needed",  "Support Needed"),
    ("general_question","General Question"),
]

class RastadUser(models.Model):
    user_id     = models.AutoField(primary_key=True)
    auth_user   = models.OneToOneField(User, on_delete=models.CASCADE,
                                       related_name="rastad_profile")
    name        = models.CharField(max_length=255)
    segment     = models.CharField(max_length=50, choices=SEGMENT_CHOICES,
                                   default="new_user")
    created_at  = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "rastad_users"

    def __str__(self):
        return f"{self.name} (#{self.user_id})"
```

**`user_id`** is `AutoField` (integer, auto-increment, 1, 2, 3...). The DB assigns it.
When a user registers, `user_id` is created automatically — no caller-supplied ID needed.
When the API is called externally with a `user_id`, we look up by this field.

---

### Message

```python
# apps/messages/models.py

from django.db import models
from apps.users.models import RastadUser

INTENT_CHOICES = [
    ("vip_question",         "VIP Question"),
    ("exchange_registration","Exchange Registration"),
    ("kol_collaboration",    "KOL Collaboration"),
    ("support_request",      "Support Request"),
    ("general_info",         "General Info"),
    ("unknown",              "Unknown"),
]

class Message(models.Model):
    user                = models.ForeignKey(RastadUser, on_delete=models.CASCADE,
                                            related_name="messages")
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

    def __str__(self):
        return f"Message #{self.id} from user #{self.user_id}"
```

---

### KnowledgeChunk

```python
# apps/knowledge/models.py

from django.db import models
from pgvector.django import VectorField

class KnowledgeChunk(models.Model):
    source_file  = models.CharField(max_length=255)
    chunk_index  = models.IntegerField()
    content      = models.TextField()
    content_hash = models.CharField(max_length=32)   # MD5 hex digest
    embedding    = VectorField(dimensions=1536)

    class Meta:
        db_table = "knowledge_chunks"
        unique_together = [("source_file", "chunk_index")]
        indexes = [
            models.Index(fields=["source_file", "chunk_index"],
                         name="idx_chunk_lookup"),
        ]

    def __str__(self):
        return f"{self.source_file}:chunk_{self.chunk_index}"
```

The `ivfflat` index for fast vector search is added via raw SQL migration
(Django does not generate it automatically — see Section 5 below).

---

## 3. Field Type Decisions

| Field | Type | Reason |
|---|---|---|
| `user_id` | AutoField (int PK) | Simple 1,2,3 IDs, DB-assigned, no collision risk |
| `auth_user` | OneToOneField | 1:1 link — one login account per Rastad user |
| `segment` | CharField with choices | Validated at app level via DRF serializer |
| `last_seen_at` | DateTimeField(auto_now=True) | Updated on every save — no manual tracking |
| `user_message` | TextField | No length limit — user messages can be long |
| `intent` | CharField with choices | Limited enum — choices enforce data quality |
| `needs_human_support` | BooleanField | Not null, always set by EvaluatorService |
| `content_hash` | CharField(32) | MD5 hex — used to skip re-embedding unchanged chunks |
| `embedding` | VectorField(1536) | Dimension must match the OpenRouter embedding model output |

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
that uses `VectorField`. This is done with a `RunSQL` step in a dedicated migration
that must run first.

### Migration 0001 — enable pgvector extension

```python
# apps/knowledge/migrations/0001_enable_pgvector.py

from django.db import migrations

class Migration(migrations.Migration):
    dependencies = []

    operations = [
        migrations.RunSQL(
            sql="CREATE EXTENSION IF NOT EXISTS vector;",
            reverse_sql="DROP EXTENSION IF EXISTS vector;",
        )
    ]
```

### Migration 0002 — create KnowledgeChunk table

Normal Django `CreateModel` migration generated by `makemigrations`.
Must declare dependency on `0001_enable_pgvector`.

### Migration 0003 — add ivfflat index

```python
# apps/knowledge/migrations/0003_add_vector_index.py

from django.db import migrations

class Migration(migrations.Migration):
    dependencies = [("knowledge", "0002_knowledgechunk")]

    operations = [
        migrations.RunSQL(
            sql="""
                CREATE INDEX IF NOT EXISTS idx_chunk_embedding_ivfflat
                ON knowledge_chunks
                USING ivfflat (embedding vector_cosine_ops)
                WITH (lists = 10);
            """,
            reverse_sql="DROP INDEX IF EXISTS idx_chunk_embedding_ivfflat;",
        )
    ]
```

`lists = 10` is appropriate for < 1000 vectors. Formula: `lists ≈ rows / 100`.

---

## 6. Signup Flow — Auth + RastadUser Creation

Both records created atomically in one database transaction.
If either fails, neither is committed.

```python
# In the signup service (pseudocode)

with transaction.atomic():
    auth_user = User.objects.create_user(
        username=username,
        password=password,
    )
    rastad_user = RastadUser.objects.create(
        auth_user=auth_user,
        name=name,
        segment="new_user",
    )
# rastad_user.user_id is now auto-assigned (1, 2, 3...)
```

After login, `request.user.rastad_profile.user_id` gives the integer user_id for that session.
The UI passes this automatically to `POST /api/message` — no manual user_id entry needed.

---

## 7. Database Configuration (docker-compose)

```yaml
postgres:
  image: pgvector/pgvector:pg16   # official image with pgvector pre-installed
  environment:
    POSTGRES_DB: rastad_db
    POSTGRES_USER: rastad
    POSTGRES_PASSWORD: ${DB_PASSWORD}
  volumes:
    - postgres_data:/var/lib/postgresql/data
```

Using `pgvector/pgvector:pg16` — the official image that ships with pgvector installed.
No manual `apt install` required inside the container.
`CREATE EXTENSION IF NOT EXISTS vector;` in migration 0001 activates it per-database.
