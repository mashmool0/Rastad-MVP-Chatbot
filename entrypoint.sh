#!/bin/bash
set -e

echo "[BOOT] Waiting for PostgreSQL at $DB_HOST:$DB_PORT..."
python - <<'EOF'
import socket, time, os, sys
host = os.environ.get("DB_HOST", "localhost")
port = int(os.environ.get("DB_PORT", "5432"))
for _ in range(30):
    try:
        socket.create_connection((host, port), timeout=2).close()
        print(f"[BOOT] PostgreSQL is up.")
        sys.exit(0)
    except OSError:
        time.sleep(1)
print("[BOOT] ERROR: could not reach PostgreSQL after 30 seconds.")
sys.exit(1)
EOF

echo "[BOOT] Running migrations..."
python manage.py migrate --noinput

echo "[BOOT] Indexing knowledge base..."
python manage.py index_knowledge_base

echo "[BOOT] Starting server..."
exec python manage.py runserver 0.0.0.0:8000
