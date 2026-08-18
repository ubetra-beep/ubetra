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

`mobile/dist` is bind-mounted read-only so a built APK is downloadable from Settings.

Instructor media is a **separate** bind-mount of the Gluetun drop folder (read-only inside UBETRA):

```
/home/james/vault/redgifs   →  /app/backend/data/redgifs
```

Each subdirectory is a playlist. Override the host path with `UBETRA_REDGIFS_HOST` (for example `/homes/james/vault/redgifs` if that is where files land). Gluetun is **not** in this compose file.

## Important env vars

| Variable | Purpose |
|----------|---------|
| `UBETRA_SECRET_KEY` | Session signing — change this |
| `UBETRA_PUBLIC_APP_URL` | Public HTTPS URL |
| `UBETRA_GEMINI_API_KEY` | Optional server-default Gemini key |
| `UBETRA_MFA_REQUIRED` | Email OTP |
| `UBETRA_ALLOW_PUBLIC_REGISTER` | Open registration |
| `UBETRA_SMTP_*` | SMTP for MFA codes **and** password-reset emails (code + link) |
| `UBETRA_GOOGLE_*` | Google OAuth (Tasks; Fitness sleep is unused if you use Health Connect) |
| `UBETRA_GARMIN_*` | Optional Garmin Wellness sleep OAuth |
| `UBETRA_VAPID_CONTACT` | Web Push contact (`mailto:…`) |
| `UBETRA_REDGIFS_HOST` | Host path bind-mounted as Instructor playlists (default `/home/james/vault/redgifs`) |
| `UBETRA_REDGIFS_DIR` | Path **inside** the container (default `/app/backend/data/redgifs`) |

Health Connect sleep/cycle sync is **on the phone**, not a Google cloud login.

## HTTPS

Use Caddy/Nginx/Traefik in front of port 8000. Example snippet: [`deploy/caddy/`](https://github.com/ubetra-beep/ubetra/tree/main/deploy/caddy).

Push + Install-app need a **secure context**.

## Backups

Copy the SQLite file under `backend/data/` (or the Docker volume) and any user **Settings → Backup** exports. Treat both as confidential.
