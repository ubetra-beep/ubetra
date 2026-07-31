from pathlib import Path

from pydantic_settings import BaseSettings

ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT_DIR / "backend" / "data"
DB_PATH = DATA_DIR / "ubetra.db"
CATALOG_PATH = DATA_DIR / "interest_catalog.json"


class Settings(BaseSettings):
    secret_key: str = "dev-only-change-me-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24 * 7
    database_url: str = f"sqlite:///{DB_PATH.as_posix()}"
    cors_origins: list[str] = ["http://localhost:8000", "http://127.0.0.1:8000"]
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash"
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://127.0.0.1:8000/api/google/callback"
    public_app_url: str = "http://127.0.0.1:8000"
    mfa_required: bool = False
    mfa_log_codes: bool = False
    allow_public_register: bool = True
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_tls: bool = True

    class Config:
        env_prefix = "UBETRA_"
        env_file = str(ROOT_DIR / ".env")
        env_file_encoding = "utf-8"


settings = Settings()

# Allow the public HTTPS origin when configured (Caddy / DuckDNS).
if settings.public_app_url and settings.public_app_url not in settings.cors_origins:
    settings.cors_origins = [*settings.cors_origins, settings.public_app_url]
