#!/usr/bin/env bash
# Call OpenRouter chat/completions with openrouter/auto — bypasses UBETRA entirely.
# Usage:
#   export OPENROUTER_API_KEY='sk-or-v1-…'
#   ./test-openrouter-direct.sh
set -euo pipefail

KEY="${OPENROUTER_API_KEY:-}"
MODEL="${OPENROUTER_MODEL:-openrouter/auto}"
REFERER="${OPENROUTER_HTTP_REFERER:-https://ubetra.local}"

if [[ -z "$KEY" ]]; then
  echo "Set OPENROUTER_API_KEY first (sk-or-v1-…)." >&2
  exit 2
fi

TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT

HTTP="$(
  curl -sS -o "$TMP" -w '%{http_code}' \
    https://openrouter.ai/api/v1/chat/completions \
    -H "Authorization: Bearer ${KEY}" \
    -H "Content-Type: application/json" \
    -H "HTTP-Referer: ${REFERER}" \
    -H "X-Title: UBETRA-diag" \
    -d "$(cat <<EOF
{
  "model": "${MODEL}",
  "messages": [
    {"role": "system", "content": "Reply with exactly: UBETRA_OK"},
    {"role": "user", "content": "connectivity probe"}
  ],
  "temperature": 0
}
EOF
)"
)"

echo "HTTP ${HTTP}"
if command -v python3 >/dev/null 2>&1; then
  python3 - "$TMP" <<'PY'
import json, sys
raw = open(sys.argv[1], encoding="utf-8").read()
try:
    data = json.loads(raw)
except json.JSONDecodeError:
    print(raw[:800])
    raise SystemExit(0)
err = data.get("error")
if err:
    if isinstance(err, dict):
        print("error:", err.get("message") or err)
    else:
        print("error:", err)
else:
    try:
        print("model_used:", data.get("model"))
        print("reply:", data["choices"][0]["message"]["content"][:240])
    except (KeyError, IndexError, TypeError):
        print(json.dumps(data, indent=2)[:800])
PY
else
  head -c 800 "$TMP"; echo
fi

[[ "$HTTP" == "200" ]]
