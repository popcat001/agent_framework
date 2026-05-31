"""Web backend configuration — loads from .env at project root."""

import os
from pathlib import Path

from dotenv import load_dotenv


def _detect_project_root() -> Path:
    """Auto-detect the project root directory.

    Resolution order:
    1. AGENT_PROJECT_ROOT env var (explicit override)
    2. Walk up from this file looking for a directory that contains
       a .env file or a prompts/ directory (project markers)
    3. Fallback: 3 levels up (assumes framework/web/backend/config.py)
    """
    if env_root := os.getenv("AGENT_PROJECT_ROOT"):
        return Path(env_root).resolve()

    here = Path(__file__).resolve().parent  # web/backend/
    # Check 2 levels up (standalone: web/backend -> repo root)
    # and 3 levels up (submodule: framework/web/backend -> project root)
    for levels in (2, 3):
        candidate = here
        for _ in range(levels):
            candidate = candidate.parent
        if (candidate / ".env").exists() or (candidate / "prompts").exists():
            return candidate

    return here.parent.parent.parent  # default: 3 levels up


PROJECT_ROOT = _detect_project_root()
load_dotenv(PROJECT_ROOT / ".env", override=True)

# --- Database (reuse existing PostgreSQL) ---
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "rtb")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD") or os.getenv("DB_PWD", "")

DATABASE_URL = f"postgresql+asyncpg://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}?ssl=require"
DATABASE_URL_SYNC = f"postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}?sslmode=require"

# --- App identity ---
APP_NAME = os.getenv("APP_NAME", "Agent")

# --- Dev mode (bypass auth) ---
DEV_MODE = os.getenv("DEV_MODE", "false").lower() in ("true", "1", "yes")
TEST_USER_EMAIL = os.getenv("TEST_USER_EMAIL", "dev@agent.local")

# --- CORS ---
CORS_ORIGINS = [
    "http://localhost:5173",  # Vite dev server
    "http://localhost:3000",
]

# --- Paths ---
TMP_DIR = PROJECT_ROOT / "tmp"
