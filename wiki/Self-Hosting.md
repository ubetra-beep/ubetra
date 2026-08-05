# Self-Hosting

UBETRA is **not** a hosted SaaS. You run it.

## Native

See the [README quick start](https://github.com/ubetra-beep/ubetra#quick-start-native--no-docker).

```bash
cp .env.example .env
# set UBETRA_SECRET_KEY
python -m venv .venv
# activate, then:
pip install -r requirements.txt
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

## Docker

```bash
cp .env.example .env
docker compose up -d --build
```

Data persists in the `ubetra-data` volume. Optional: `UBETRA_HOST_PORT=18000` if 8000 is taken.

## Important env vars

| Variable | Purpose |
|----------|---------|
| `UBETRA_SECRET_KEY` | Session signing — change this |
| `UBETRA_PUBLIC_APP_URL` | Public HTTPS URL |
| `UBETRA_GEMINI_API_KEY` | Optional server-default Gemini key |
| `UBETRA_MFA_REQUIRED` | Email OTP |
| `UBETRA_ALLOW_PUBLIC_REGISTER` | Open registration |
| `UBETRA_SMTP_*` | SMTP for MFA codes **and** password-reset emails (code + link) |
| `UBETRA_GOOGLE_*` | Google OAuth (Tasks + Fitness sleep redirect) |
| `UBETRA_GARMIN_*` | Optional Garmin Wellness sleep OAuth |
| `UBETRA_VAPID_CONTACT` | Web Push contact (`mailto:…`) |

## HTTPS

Use Caddy/Nginx/Traefik in front of port 8000. Example snippet: [`deploy/caddy/`](https://github.com/ubetra-beep/ubetra/tree/main/deploy/caddy).

Push + Install-app need a **secure context**.

## Backups

Copy the SQLite file under `backend/data/` (or the Docker volume) and any user **Settings → Backup** exports. Treat both as confidential.
