from pathlib import Path
import json

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .catalog import ensure_data_dir, seed_catalog
from .config import ROOT_DIR, settings
from .services.vapid import ensure_vapid_keys
from .database import Base, SessionLocal, engine
from .migrate import run_migrations
from .routers import (
    account,
    acts,
    assistant,
    auth,
    chastity,
    context_links,
    core_knowledge,
    dynamics,
    feelings,
    gear,
    google_tasks,
    interests,
    interview,
    journals,
    manga,
    onboarding,
    org_tracking,
    history_dashboard,
    agreements,
    chat,
    push,
    punishments,
    settings as settings_router,
    sleep,
    cycle,
    tasks,
    vault,
)

HAR_CATALOG = Path(
    r"C:\Users\james\Documents\artebu-source\api.artebu.com\dynamic\sex_interests!dynamic_token=dynamic_QVgVAZ5NjWtB"
)

FRONTEND_DIR = ROOT_DIR / "frontend"
ICON_STYLES = ("violet", "sage", "midnight", "ember", "cream")
DEFAULT_ICON_STYLE = "violet"

app = FastAPI(title="UBETRA", version="0.75")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins + ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api")
app.include_router(account.router, prefix="/api")
app.include_router(dynamics.router, prefix="/api")
app.include_router(interests.router, prefix="/api")
app.include_router(core_knowledge.router, prefix="/api")
app.include_router(assistant.router, prefix="/api")
app.include_router(interview.router, prefix="/api")
app.include_router(onboarding.router, prefix="/api")
app.include_router(context_links.router, prefix="/api")
app.include_router(journals.router, prefix="/api")
app.include_router(org_tracking.router, prefix="/api")
app.include_router(feelings.router, prefix="/api")
app.include_router(punishments.router, prefix="/api")
app.include_router(history_dashboard.router, prefix="/api")
app.include_router(chastity.router, prefix="/api")
app.include_router(agreements.router, prefix="/api")
app.include_router(acts.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
app.include_router(gear.router, prefix="/api")
app.include_router(vault.router, prefix="/api")
app.include_router(google_tasks.router, prefix="/api")
app.include_router(sleep.router, prefix="/api")
app.include_router(sleep.callback_router, prefix="/api")
app.include_router(cycle.router, prefix="/api")
app.include_router(manga.router, prefix="/api")
app.include_router(push.router, prefix="/api")
app.include_router(settings_router.router, prefix="/api")
app.include_router(tasks.router, prefix="/api")


@app.on_event("startup")
def on_startup() -> None:
    ensure_data_dir()
    ensure_vapid_keys()
    Base.metadata.create_all(bind=engine)
    run_migrations()
    db = SessionLocal()
    try:
        seed_catalog(db, har_fallback=HAR_CATALOG if HAR_CATALOG.exists() else None)
        from .services.feelings import seed_feeling_emotions

        seed_feeling_emotions(db)
        db.commit()
    finally:
        db.close()


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


APK_DIST = ROOT_DIR / "mobile" / "dist"


def _published_apk() -> Path | None:
    for name in ("ubetra.apk", "ubetra-debug.apk"):
        path = APK_DIST / name
        if path.is_file() and path.stat().st_size > 0:
            return path
    return None


@app.get("/api/app/android")
def android_apk_status() -> dict:
    apk = _published_apk()
    meta: dict = {}
    meta_path = APK_DIST / "ubetra.json"
    if meta_path.is_file():
        try:
            loaded = json.loads(meta_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                meta = loaded
        except json.JSONDecodeError:
            meta = {}
    if apk is None:
        return {
            "available": False,
            "version": meta.get("version") or "",
            "version_code": int(meta.get("version_code") or 0),
            "built_at": meta.get("built_at") or "",
            "size": 0,
            "url": "/apk/ubetra.apk",
        }
    return {
        "available": True,
        "version": str(meta.get("version") or "debug"),
        "version_code": int(meta.get("version_code") or 0),
        "built_at": str(meta.get("built_at") or ""),
        "size": apk.stat().st_size,
        "url": "/apk/ubetra.apk",
    }


@app.get("/apk/ubetra.apk")
def download_android_apk() -> FileResponse:
    apk = _published_apk()
    if apk is None:
        raise HTTPException(status_code=404, detail="Android APK is not published on this server.")
    return FileResponse(
        apk,
        media_type="application/vnd.android.package-archive",
        filename="ubetra.apk",
        headers={"Cache-Control": "no-cache"},
    )


if FRONTEND_DIR.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIR), name="assets")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(FRONTEND_DIR / "index.html")

    @app.get("/manifest.webmanifest")
    def manifest(request: Request, style: str = "") -> JSONResponse:
        chosen = (style or request.cookies.get("ubetra_icon_style") or DEFAULT_ICON_STYLE).strip().lower()
        if chosen not in ICON_STYLES:
            chosen = DEFAULT_ICON_STYLE
        prefix = f"/icons/{chosen}"
        return JSONResponse(
            {
                "id": "/",
                "name": "Shared space",
                "short_name": "Space",
                "description": "Private shared planner",
                "start_url": "/",
                "scope": "/",
                "display": "standalone",
                "display_override": ["standalone", "minimal-ui"],
                "background_color": "#1a1a1a",
                "theme_color": "#1a1a1a",
                "orientation": "portrait-primary",
                "icons": [
                    {
                        "src": f"{prefix}/icon-192.png",
                        "sizes": "192x192",
                        "type": "image/png",
                        "purpose": "any",
                    },
                    {
                        "src": f"{prefix}/icon-512.png",
                        "sizes": "512x512",
                        "type": "image/png",
                        "purpose": "any",
                    },
                    {
                        "src": f"{prefix}/icon-512-maskable.png",
                        "sizes": "512x512",
                        "type": "image/png",
                        "purpose": "maskable",
                    },
                ],
            },
            media_type="application/manifest+json",
            headers={"Cache-Control": "no-cache"},
        )

    @app.get("/sw.js")
    def service_worker() -> FileResponse:
        return FileResponse(
            FRONTEND_DIR / "sw.js",
            media_type="application/javascript",
            headers={"Cache-Control": "no-cache"},
        )

    icons_dir = FRONTEND_DIR / "icons"
    if icons_dir.is_dir():
        app.mount("/icons", StaticFiles(directory=icons_dir), name="icons")

    @app.get("/settings")
    def settings_spa_redirect(request: Request) -> RedirectResponse:
        """Legacy path links (e.g. chat key redeem) → hash-routed SPA."""
        qs = request.url.query
        target = "/#/settings" + (f"?{qs}" if qs else "")
        return RedirectResponse(url=target, status_code=302)