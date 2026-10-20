#!/usr/bin/env bash
# Show account vs shared LLM config from the live ubetra container DB (keys masked).
# Usage:
#   ./inspect-llm-db.sh
#   UBETRA_DB=/path/to/ubetra.db ./inspect-llm-db.sh   # host-side file instead
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
PY="$ROOT/help/for-Sindy/scripts/inspect_llm_db.py"
CONTAINER="${UBETRA_CONTAINER:-ubetra}"

if [[ -n "${UBETRA_DB:-}" ]]; then
  exec python3 "$PY"
fi

if ! docker inspect "$CONTAINER" >/dev/null 2>&1; then
  echo "Container '$CONTAINER' not found. Set UBETRA_CONTAINER=… or UBETRA_DB=/path/to/ubetra.db" >&2
  exit 1
fi

docker exec -i -e UBETRA_DB=/app/backend/data/ubetra.db "$CONTAINER" python - < "$PY"
