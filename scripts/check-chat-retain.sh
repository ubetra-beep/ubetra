#!/bin/bash
set -euo pipefail
curl -s http://127.0.0.1:18000/api/health; echo
curl -s http://127.0.0.1:18000/sw.js | head -c 40; echo
docker exec -e PYTHONPATH=/app -w /app ubetra python <<'PY'
from backend.app.database import SessionLocal
from backend.app.models import Dynamic
db = SessionLocal()
for d in db.query(Dynamic).all():
    print(d.invite_code, "retain", d.chat_retain_history, "expire_h", d.chat_expire_hours)
PY
