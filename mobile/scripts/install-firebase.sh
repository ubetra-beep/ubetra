#!/usr/bin/env bash
# Install Firebase credentials for UBETRA native FCM on Docker-SVR.
# Usage:
#   1. Copy google-services.json → ~/docker/ubetra/mobile/google-services.json
#   2. Copy service-account JSON → ~/docker/ubetra/backend/data/fcm-service-account.json
#   3. bash mobile/scripts/install-firebase.sh
#   4. Rebuild APK: bash mobile/scripts/build-apk.sh
#   5. Redeploy/restart ubetra container so env is picked up
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
MOBILE="$ROOT/mobile"
DATA="$ROOT/backend/data"
ENV_FILE="$ROOT/.env"
GS_SRC="${1:-$MOBILE/google-services.json}"
SA_SRC="${2:-$DATA/fcm-service-account.json}"

if [[ ! -f "$GS_SRC" ]]; then
  echo "Missing google-services.json at $GS_SRC" >&2
  exit 1
fi
if [[ ! -f "$SA_SRC" ]]; then
  echo "Missing FCM service account JSON at $SA_SRC" >&2
  exit 1
fi

mkdir -p "$MOBILE/android/app" "$DATA"
cp -f "$GS_SRC" "$MOBILE/google-services.json"
cp -f "$GS_SRC" "$MOBILE/android/app/google-services.json"
chmod 600 "$SA_SRC"

PROJECT_ID="$(python3 - <<PY
import json
print(json.load(open("$SA_SRC")).get("project_id",""))
PY
)"
if [[ -z "$PROJECT_ID" ]]; then
  echo "Could not read project_id from service account JSON" >&2
  exit 1
fi

touch "$ENV_FILE"
grep -q '^UBETRA_FCM_SERVICE_ACCOUNT_FILE=' "$ENV_FILE" 2>/dev/null \
  && sed -i "s|^UBETRA_FCM_SERVICE_ACCOUNT_FILE=.*|UBETRA_FCM_SERVICE_ACCOUNT_FILE=/app/backend/data/fcm-service-account.json|" "$ENV_FILE" \
  || echo "UBETRA_FCM_SERVICE_ACCOUNT_FILE=/app/backend/data/fcm-service-account.json" >> "$ENV_FILE"
grep -q '^UBETRA_FCM_PROJECT_ID=' "$ENV_FILE" 2>/dev/null \
  && sed -i "s|^UBETRA_FCM_PROJECT_ID=.*|UBETRA_FCM_PROJECT_ID=$PROJECT_ID|" "$ENV_FILE" \
  || echo "UBETRA_FCM_PROJECT_ID=$PROJECT_ID" >> "$ENV_FILE"

# Ensure service account lives at the path the container mounts
if [[ "$(realpath "$SA_SRC")" != "$(realpath "$DATA/fcm-service-account.json")" ]]; then
  cp -f "$SA_SRC" "$DATA/fcm-service-account.json"
  chmod 600 "$DATA/fcm-service-account.json"
fi

echo "Installed:"
echo "  google-services.json → mobile/ + android/app/"
echo "  service account → backend/data/fcm-service-account.json"
echo "  .env UBETRA_FCM_PROJECT_ID=$PROJECT_ID"
echo
echo "Next:"
echo "  cd $ROOT && docker compose up -d  # pick up .env"
echo "  bash mobile/scripts/build-apk.sh"
echo "  Install new APK, open app, Settings → Notify this device"
