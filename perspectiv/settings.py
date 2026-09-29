from __future__ import annotations

import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
REPORT_DIR = BASE_DIR / "reports"

DATA_DIR.mkdir(exist_ok=True)
REPORT_DIR.mkdir(exist_ok=True)

DATABASE_URL = os.getenv("PERSPECTIV_DATABASE_URL", f"sqlite:///{DATA_DIR / 'perspectiv.db'}")


def env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


ENVIRONMENT = os.getenv("PERSPECTIV_ENV", "development").strip().lower()
PUBLIC_URL = os.getenv("PERSPECTIV_PUBLIC_URL", "http://127.0.0.1:8000").rstrip("/")
OIDC_ISSUER = os.getenv("PERSPECTIV_OIDC_ISSUER", "").rstrip("/")
OIDC_AUDIENCE = os.getenv("PERSPECTIV_OIDC_AUDIENCE", "perspectiv-api")
OIDC_JWKS_URL = os.getenv("PERSPECTIV_OIDC_JWKS_URL", "")
AUTH_DISABLED = env_bool("PERSPECTIV_AUTH_DISABLED", False)
MCP_ALLOWED_HOSTS = [
    value.strip() for value in os.getenv("PERSPECTIV_MCP_ALLOWED_HOSTS", "127.0.0.1:*,localhost:*").split(",") if value.strip()
]
MCP_ALLOWED_ORIGINS = [
    value.strip()
    for value in os.getenv("PERSPECTIV_MCP_ALLOWED_ORIGINS", "http://127.0.0.1:*,http://localhost:*").split(",")
    if value.strip()
]
DELETE_CONFIRMATION_TTL_SECONDS = int(os.getenv("PERSPECTIV_DELETE_CONFIRMATION_TTL", "300"))
BOOTSTRAP_ADMIN_USERNAME = os.getenv("PERSPECTIV_BOOTSTRAP_ADMIN_USERNAME", "admin").strip().lower()
BOOTSTRAP_ADMIN_NAME = os.getenv("PERSPECTIV_BOOTSTRAP_ADMIN_NAME", "Administrateur").strip()
BOOTSTRAP_ADMIN_EMAIL = os.getenv("PERSPECTIV_BOOTSTRAP_ADMIN_EMAIL", "").strip()
BOOTSTRAP_ADMIN_PASSWORD = os.getenv("PERSPECTIV_BOOTSTRAP_ADMIN_PASSWORD", "")
