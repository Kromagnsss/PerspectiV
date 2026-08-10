from __future__ import annotations

import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
REPORT_DIR = BASE_DIR / "reports"

DATA_DIR.mkdir(exist_ok=True)
REPORT_DIR.mkdir(exist_ok=True)

DATABASE_URL = os.getenv("PERSPECTIV_DATABASE_URL", f"sqlite:///{DATA_DIR / 'perspectiv.db'}")
