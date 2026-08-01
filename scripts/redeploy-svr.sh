#!/bin/bash
set -euo pipefail
cd ~/docker/ubetra
# Avoid Compose merging duplicate host ports
python3 - <<'PY'
from pathlib import Path
import re
p = Path("docker-compose.yml")
if p.exists():
    t = p.read_text()
    t2 = re.sub(r"\n    ports:\n(?:      - .*\n)+", "\n", t)
    # ensure override supplies 18000; if base had ports via env, restore single mapping in override only
    p.write_text(t2)
PY
# Prefer override ports only
if ! grep -q '18000:8000' docker-compose.override.yml 2>/dev/null; then
  cat > docker-compose.override.yml <<'EOF'
services:
  ubetra:
    image: ubetra:local
    ports:
      - "18000:8000"
    networks:
      - edge
networks:
  edge:
    external: true
    name: edge
EOF
fi
grep -q '^UBETRA_HOST_PORT=' .env 2>/dev/null || echo 'UBETRA_HOST_PORT=18000' >> .env
docker compose up -d --build
sleep 2
curl -s http://127.0.0.1:18000/api/health; echo
curl -s http://127.0.0.1:18000/sw.js | head -c 40; echo
docker exec ubetra python - <<'PY'
from backend.app.database import SessionLocal
from backend.app.models import Dynamic
db = SessionLocal()
for d in db.query(Dynamic).all():
    print(d.invite_code, "retain", d.chat_retain_history, "expire_h", d.chat_expire_hours)
PY
