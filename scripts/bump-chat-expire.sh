#!/bin/bash
set -euo pipefail
docker exec -e PYTHONPATH=/app -w /app ubetra python <<'PY'
from backend.app.database import SessionLocal
from backend.app.models import Dynamic
db = SessionLocal()
for d in db.query(Dynamic).all():
    # Ensure timed-cache fallback is 30 days if forever is turned off later.
    if (d.chat_expire_hours or 0) < 720:
        d.chat_expire_hours = 720
    # Forever retention already covers offline/multi-device; leave it on if set.
    print("before-commit", d.invite_code, "retain", d.chat_retain_history, "expire", d.chat_expire_hours)
db.commit()
for d in db.query(Dynamic).all():
    print("after", d.invite_code, "retain", d.chat_retain_history, "expire", d.chat_expire_hours)
PY
