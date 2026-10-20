# OpenRouter troubleshooting (for Sindy)

Ad-hoc guide when **Settings → AI → Test AI connection** fails with **400** in the Docker logs, even though OpenRouter is selected and a key looks saved.

```text
POST /api/settings/llm/test?dynamic_id=… HTTP/1.1" 400
```

## What that 400 actually means

In current UBETRA, `/api/settings/llm/test` returns **400 only when the resolved config has no API key**.

It does **not** mean:

- `openrouter/auto` is invalid (it is a real OpenRouter model)
- Custom model must be filled in (leave it blank)
- OpenRouter rejected the chat request

If OpenRouter itself rejects the call, Test usually returns **HTTP 200** with JSON like `{ "ok": false, "detail": "LLM error: …" }`, or other routes show **502** with `LLM error: …`.

### Account key vs shared (dynamic) key

The API key field placeholder (`Saved key ••••abcd`) is your **account** key.

**Test AI connection** (when a dynamic is selected) prefers the **shared key on that dynamic**. Those can disagree:

| What you see | What Test uses |
|---|---|
| Account key saved → placeholder shows `••••3f17` | Shared key for `dynamic_id=…` (may be empty) |

That mismatch is the usual cause of exactly: UI shows a saved key + Docker log `400` on `/settings/llm/test`.

---

## Fix in the app (try this first)

1. Open **Settings → AI & assistant → Show keys and connections**.
2. Provider: **OpenRouter**. Model: **openrouter/auto**. Custom model: **blank**.
3. Paste your OpenRouter key again (`sk-or-v1-…`) into **API key** — do not leave it blank this time.
4. **Save**.
5. Tap **Test AI connection**.

Success looks like:

```text
AI test OK · openrouter / openrouter/auto · shared key · …
```

If the page says **Shared AI key is active**, open **Advanced — use a different LLM…** if needed, paste the key there, and Save again so the shared path updates.

Named connections / Batch test are separate. The button that hits `/settings/llm/test` uses **account/shared LLM settings only**, not named AI routing.

---

## Step-by-step diagnostics on the Docker host

Run these on the machine that runs the `ubetra` container. From a clone of this repo:

```bash
cd /path/to/ubetra
chmod +x help/for-Sindy/scripts/*.sh
```

### 1) Confirm the container and health

```bash
docker ps --filter name=ubetra
curl -sS http://127.0.0.1:8000/api/health
# If you mapped a different host port (compose UBETRA_HOST_PORT), use that instead of 8000.
```

### 2) Is OpenRouter reachable from inside the container?

Outbound HTTPS must work from the container (not only from your laptop):

```bash
docker exec ubetra python -c "import urllib.request; print(urllib.request.urlopen('https://openrouter.ai/api/v1/models', timeout=20).status)"
```

Expect `200`. Timeouts / DNS errors mean firewall, DNS, or no egress — fix network before chasing keys.

### 3) Test your OpenRouter key directly (bypass UBETRA)

```bash
export OPENROUTER_API_KEY='sk-or-v1-…'   # paste your key; do not commit it
./help/for-Sindy/scripts/test-openrouter-direct.sh
```

- **401** → bad/revoked key  
- **402** → no credits on the OpenRouter account  
- **200** + a short reply → key and `openrouter/auto` are fine; the bug is inside UBETRA config sync

### 4) Inspect account vs shared keys in the database (no secrets printed)

```bash
./help/for-Sindy/scripts/inspect-llm-db.sh
```

Or point at a copied DB file:

```bash
UBETRA_DB=/path/to/ubetra.db ./help/for-Sindy/scripts/inspect-llm-db.sh
```

Look for the dynamic you are testing (`dynamic_id` from the Docker log). You want:

- `users.llm_provider` / `llm_model` = `openrouter` / `openrouter/auto`
- `users` has `api_key_set: yes` **and**
- that dynamic has `shared_api_key_set: yes`

If account is yes and shared is **no**, re-paste + Save in Settings (step above), then re-run this script.

### 5) Call UBETRA’s Test endpoint like the app does

You need a logged-in session token (same value as browser `localStorage.ubetra_token`, or from a fresh login):

```bash
export UBETRA_BASE='http://127.0.0.1:8000'          # host URL that reaches the app
export UBETRA_TOKEN='…'                              # Bearer token
export UBETRA_DYNAMIC_ID='a70b4ec6-…'                 # from the failing log line
./help/for-Sindy/scripts/test-ubetra-llm.sh
```

Interpret:

| HTTP / body | Meaning |
|---|---|
| **400** + “Add an API key…” | Resolved config has no key (account/shared mismatch) |
| **200** `{ "ok": true, … }` | Fixed |
| **200** `{ "ok": false, "detail": "LLM error: …" }` | Key reached OpenRouter; read the message after `LLM error:` |

---

## OpenRouter checklist

- Key starts with `sk-or-v1-`
- Account has **credits** at [openrouter.ai/credits](https://openrouter.ai/credits)
- Model stays **`openrouter/auto`** (custom blank is correct)
- Do not paste `Bearer sk-or-…` into the field — only the key itself
- Prefer a dedicated key you can revoke

Some older model IDs in UBETRA’s dropdown may be retired on OpenRouter. **`openrouter/auto` is fine**; use Custom model only if you want a specific slug from [openrouter.ai/models](https://openrouter.ai/models).

---

## What to send back if you are still stuck

1. One Docker log line for the failing Test (method, path, status).  
2. The **red error text** from the app (exact string).  
3. Output of `inspect-llm-db.sh` (it masks keys).  
4. Output of `test-openrouter-direct.sh` **without** pasting the key (status code + error message only).  
5. Whether Test says it used `shared` or `account` key on success attempts.

Do **not** paste full API keys into chat or GitHub issues.

---

## Scripts in this folder

| Script | Purpose |
|---|---|
| [`scripts/test-openrouter-direct.sh`](scripts/test-openrouter-direct.sh) | `chat/completions` with `openrouter/auto` using `OPENROUTER_API_KEY` |
| [`scripts/inspect-llm-db.sh`](scripts/inspect-llm-db.sh) | Show account vs shared LLM fields from the live container DB |
| [`scripts/test-ubetra-llm.sh`](scripts/test-ubetra-llm.sh) | POST `/api/settings/llm/test` with your session token |
| [`scripts/inspect_llm_db.py`](scripts/inspect_llm_db.py) | Python helper used by the shell wrapper |
