from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
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
    onboarding,
    org_tracking,
    history_dashboard,
    agreements,
    chat,
    push,
    punishments,
    settings as settings_router,
    tasks,
    vault,
)

HAR_CATALOG = Path(
    r"C:\Users\james\Documents\artebu-source\api.artebu.com\dynamic\sex_interests!dynamic_token=dynamic_QVgVAZ5NjWtB"
)

FRONTEND_DIR = ROOT_DIR / "frontend"

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


if FRONTEND_DIR.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIR), name="assets")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(FRONTEND_DIR / "index.html")

    @app.get("/manifest.webmanifest")
    def manifest() -> FileResponse:
        return FileResponse(
            FRONTEND_DIR / "manifest.webmanifest",
            media_type="application/manifest+json",
        )

    @app.get("/sw.js")
    def service_worker() -> FileResponse:
        return FileResponse(FRONTEND_DIR / "sw.js")

    icons_dir = FRONTEND_DIR / "icons"
    if icons_dir.is_dir():
        app.mount("/icons", StaticFiles(directory=icons_dir), name="icons")

    @app.get("/settings")
    def settings_spa_redirect(request: Request) -> RedirectResponse:
        """Legacy path links (e.g. chat key redeem) → hash-routed SPA."""
        qs = request.url.query
        target = "/#/settings" + (f"?{qs}" if qs else "")
        return RedirectResponse(url=target, status_code=302)