# UBETRA

**Version:** `0.74` (beta)

Self-hosted private planner for consensual adult relationship dynamics. Runs as a Progressive Web App (PWA) on your own hardware — **not** a hosted SaaS.

UBETRA is free. There is no paid tier and no cloud account for the app itself. If you want to tip the developer:

**[Buy me a coffee on Ko-fi](https://ko-fi.com/ubetradev)**

---

## Who this is for

People who want to **self-host** a private couple/dynamic planner (tracking, chat, tasks, optional AI assist) on a home server, NAS, or VPS they control.

You bring your own domain/HTTPS (recommended for notifications and PWA install) and optional LLM API keys.

---

## Requirements

- **Python 3.12+** (native install), **or** Docker / Docker Compose
- A modern browser (Chrome/Edge/Firefox/Safari)
- HTTPS in production for push notifications and a proper PWA install (localhost is fine for local testing)

---

## Quick start (native — no Docker)

```bash
git clone https://github.com/ubetra-beep/ubetra.git
cd ubetra
cp .env.example .env
# edit .env — at least set UBETRA_SECRET_KEY

python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS / Linux
# source .venv/bin/activate

pip install -r requirements.txt
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000**

### Windows helpers

After the venv exists once:

- `run.bat` — localhost only  
- `run.ps1` — LAN-reachable (`0.0.0.0:8000`) for phones on the same Wi‑Fi  

---

## Quick start (Docker)

### Build from this repo

```bash
git clone https://github.com/ubetra-beep/ubetra.git
cd ubetra
cp .env.example .env
# edit .env — set UBETRA_SECRET_KEY (and optional AI / SMTP vars)

docker compose up -d --build
```

App: **http://127.0.0.1:8000**  
Data persists in the `ubetra-data` Docker volume.

Optional: set `UBETRA_HOST_PORT=18000` in the environment (or a local `docker-compose.override.yml`) if port 8000 is already taken.

### Pull a published image (when available)

After the GHCR publish workflow is enabled:

```bash
export UBETRA_IMAGE=ghcr.io/ubetra-beep/ubetra:0.74
docker compose up -d
```

Until then, use **build from this repo** above. The workflow file lives at [`docs/docker-publish.yml`](docs/docker-publish.yml) — copy it to `.github/workflows/` once the GitHub CLI token has the `workflow` scope.

---

## Configuration

Copy `.env.example` → `.env`. Important variables:

| Variable | Purpose |
|----------|---------|
| `UBETRA_SECRET_KEY` | Session signing — **change this** |
| `UBETRA_PUBLIC_APP_URL` | Public HTTPS URL of your install |
| `UBETRA_GEMINI_API_KEY` | Optional server-default Gemini key |
| `UBETRA_MFA_REQUIRED` | Require email OTP (`true`/`false`) |
| `UBETRA_ALLOW_PUBLIC_REGISTER` | Open registration (`true`/`false`) |
| `UBETRA_SMTP_*` | SMTP for MFA codes |

Users can also paste their own Gemini/OpenAI keys in **Settings**. Couples can share one API key per dynamic.

### HTTPS reverse proxy

See [`deploy/caddy/ubetra.Caddyfile.snippet`](deploy/caddy/ubetra.Caddyfile.snippet) for a minimal Caddy example. Nginx/Traefik work the same way: proxy to port `8000`.

Push notifications and “Install app” need a **secure context** (HTTPS or localhost). Plain `http://192.168…` will not allow web push.

---

## Project layout

```
ubetra/
  backend/app/     FastAPI API + SQLite
  backend/seed/    Catalog seed data
  frontend/        Static PWA (HTML/CSS/JS — no build step)
  deploy/caddy/    Example reverse-proxy snippet
  VERSION          Current semver (0.x while beta)
```

---

## Status

This is a **beta (`0.x`)**. Features and APIs may change before `1.0.0`.

---

## License / usage

Self-host freely. Do not expect the maintainer to run a public multi-tenant cloud for you.

Tips welcome: **[ko-fi.com/ubetradev](https://ko-fi.com/ubetradev)**
