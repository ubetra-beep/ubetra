#!/usr/bin/env bash
# POST /api/settings/llm/test the same way the Settings UI does.
# Usage:
#   export UBETRA_BASE='http://127.0.0.1:8000'
#   export UBETRA_TOKEN='…'            # localStorage ubetra_token, or from login
#   export UBETRA_DYNAMIC_ID='…'       # optional but recommended (from Docker 400 log)
#   ./test-ubetra-llm.sh
#
# Optional login helper (writes nothing to disk):
#   export UBETRA_EMAIL='you@example.com'
#   export UBETRA_PASSWORD='…'
#   ./test-ubetra-llm.sh --login
set -euo pipefail

BASE="${UBETRA_BASE:-http://127.0.0.1:8000}"
BASE="${BASE%/}"
TOKEN="${UBETRA_TOKEN:-}"
DYNAMIC_ID="${UBETRA_DYNAMIC_ID:-}"

if [[ "${1:-}" == "--login" ]]; then
  if [[ -z "${UBETRA_EMAIL:-}" || -z "${UBETRA_PASSWORD:-}" ]]; then
    echo "For --login set UBETRA_EMAIL and UBETRA_PASSWORD." >&2
    exit 2
  fi
  LOGIN_JSON="$(
    curl -sS -X POST "$BASE/api/auth/login" \
      -H "Content-Type: application/json" \
      -d "{\"email\":$(python3 -c 'import json,os; print(json.dumps(os.environ["UBETRA_EMAIL"]))'),\"password\":$(python3 -c 'import json,os; print(json.dumps(os.environ["UBETRA_PASSWORD"]))')}"
  )"
  TOKEN="$(python3 -c 'import json,sys; d=json.loads(sys.argv[1]); print(d.get("access_token") or "")' "$LOGIN_JSON")"
  if [[ -z "$TOKEN" ]]; then
    echo "Login failed:" >&2
    echo "$LOGIN_JSON" >&2
    exit 1
  fi
  echo "Login OK (token acquired)."
fi

if [[ -z "$TOKEN" ]]; then
  echo "Set UBETRA_TOKEN, or run with --login and UBETRA_EMAIL / UBETRA_PASSWORD." >&2
  exit 2
fi

URL="$BASE/api/settings/llm/test"
if [[ -n "$DYNAMIC_ID" ]]; then
  URL="${URL}?dynamic_id=$(python3 -c 'import urllib.parse,os; print(urllib.parse.quote(os.environ["UBETRA_DYNAMIC_ID"]))')"
fi

TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT

HTTP="$(
  curl -sS -o "$TMP" -w '%{http_code}' -X POST "$URL" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "Content-Type: application/json"
)"

echo "POST $URL"
echo "HTTP ${HTTP}"
python3 - "$TMP" <<'PY'
import json, sys
raw = open(sys.argv[1], encoding="utf-8").read()
try:
    data = json.loads(raw)
except json.JSONDecodeError:
    print(raw[:800])
    raise SystemExit(0)
print(json.dumps(data, indent=2)[:2000])
detail = data.get("detail")
if isinstance(detail, str) and "API key" in detail:
    print(
        "\nInterpretation: UBETRA resolved an empty API key for this test "
        "(account placeholder can still show a saved key). Re-paste OpenRouter "
        "key in Settings and Save so the shared dynamic key syncs."
    )
elif data.get("ok") is True:
    print("\nInterpretation: connection works.")
elif data.get("ok") is False:
    print(
        "\nInterpretation: UBETRA reached a provider; read detail "
        "(OpenRouter/network/model issue)."
    )
PY
