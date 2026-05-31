"""FastAPI application entry point for the Agent Framework Web UI."""

import importlib
import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import APP_NAME, CORS_ORIGINS, DEV_MODE, PROJECT_ROOT, TMP_DIR
from database import close_db, get_db, init_db

logger = logging.getLogger(__name__)

# Ensure agent framework is importable.
# When used as submodule: PROJECT_ROOT/framework/ contains agent/
# When standalone: the repo root itself contains agent/
_framework_dir = PROJECT_ROOT / "framework"
if _framework_dir.exists():
    sys.path.insert(0, str(_framework_dir))
else:
    # Standalone mode: agent/ is a sibling of web/
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle."""
    await init_db()
    TMP_DIR.resolve().mkdir(parents=True, exist_ok=True)
    _prune_tmp_charts()
    yield
    await close_db()


def _prune_tmp_charts(max_age_days: int = 30) -> None:
    """Delete chat-chart HTML and PNG files in tmp/ older than `max_age_days`.

    Mirrors the 30-day retention previously enforced on the `web_charts` table for chat
    charts, now that chat charts are written to disk instead of the DB. The PNG sweep
    matches the HTML sibling written by tools/utils.py:waterfall_chart so bots and the
    web UI stay aligned. Globs are kept narrow (`*.html` and `*.png`) instead of `*`
    so unrelated tmp files are not touched.
    """
    import time
    try:
        cutoff = time.time() - max_age_days * 86400
        removed = 0
        for pattern in ("*.html", "*.png"):
            for f in TMP_DIR.glob(pattern):
                try:
                    if f.stat().st_mtime < cutoff:
                        f.unlink()
                        removed += 1
                except OSError:
                    pass
        if removed:
            logger.info("Pruned %d expired chart files from %s", removed, TMP_DIR)
    except Exception as e:
        logger.debug("tmp/ chart cleanup skipped: %s", e)


# Hide OpenAPI spec, Swagger UI, and ReDoc in production. The spec still
# leaks the entire endpoint map to any authenticated Adobe employee
# otherwise (audit W-04). DEV_MODE keeps them on for local development.
app = FastAPI(
    title=APP_NAME,
    version="0.1.0",
    lifespan=lifespan,
    openapi_url="/openapi.json" if DEV_MODE else None,
    docs_url="/docs" if DEV_MODE else None,
    redoc_url="/redoc" if DEV_MODE else None,
)

# Redirect Azure hostname to canonical custom domain (e.g. rtbai-stage.azurewebsites.net -> finguru.adobe.com)
# Activated only when CANONICAL_DOMAIN and WEBSITE_HOSTNAME are both set and differ.
_CANONICAL_DOMAIN = os.getenv("CANONICAL_DOMAIN")
_AZURE_HOSTNAME = os.getenv("WEBSITE_HOSTNAME")

if _CANONICAL_DOMAIN and _AZURE_HOSTNAME and _CANONICAL_DOMAIN != _AZURE_HOSTNAME:
    class CanonicalDomainMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            host = request.headers.get("host", "").split(":")[0]
            if host == _AZURE_HOSTNAME:
                url = str(request.url).replace(host, _CANONICAL_DOMAIN, 1)
                return RedirectResponse(url, status_code=301)
            return await call_next(request)

    app.add_middleware(CanonicalDomainMiddleware)

# CORS for Vite dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        resp.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; "
            "font-src 'self' data:; "
            "connect-src 'self' https://login.microsoftonline.com https://*.okta.com; "
            "frame-ancestors 'self'; "
            "object-src 'none'; "
            "base-uri 'self'",
        )
        return resp


app.add_middleware(SecurityHeadersMiddleware)

# --- Health check (must be before static mount) ---
@app.get("/api/health")
async def health():
    return {"status": "ok", "service": APP_NAME.lower()}


# --- Routers ---
from routers.admin import router as admin_router
from routers.agents import router as agents_router
from routers.auth import router as auth_router
from routers.chat import router as chat_router
from routers.conversations import router as conversations_router

app.include_router(auth_router, prefix="/api/auth", tags=["auth"])
app.include_router(agents_router, prefix="/api/agents", tags=["agents"])
app.include_router(admin_router, prefix="/api/admin", tags=["admin"])
app.include_router(conversations_router, prefix="/api/conversations", tags=["conversations"])
app.include_router(chat_router, tags=["chat"])

# --- Project-specific routers (auto-discovered from {PROJECT_ROOT}/web/backend/routers/) ---
_project_backend = PROJECT_ROOT / "web" / "backend"
if _project_backend.exists() and str(_project_backend) not in sys.path:
    sys.path.insert(0, str(_project_backend))

_project_routers_dir = _project_backend / "routers"
if _project_routers_dir.is_dir():
    for router_file in sorted(_project_routers_dir.glob("*.py")):
        if router_file.name.startswith("_"):
            continue
        module_name = f"project_routers_{router_file.stem}"
        try:
            # Use spec-based import to avoid conflicts with framework's routers/ package
            spec = importlib.util.spec_from_file_location(module_name, str(router_file))
            mod = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = mod
            spec.loader.exec_module(mod)

            router_obj = getattr(mod, "router", None)
            if router_obj:
                prefix = getattr(mod, "PREFIX", f"/api/{router_file.stem}")
                tags = getattr(mod, "TAGS", [router_file.stem])
                app.include_router(router_obj, prefix=prefix, tags=tags)
                logger.info("Loaded project router: %s -> %s", router_file.name, prefix)
        except Exception as e:
            logger.warning("Failed to load project router %s: %s", router_file.name, e)

# Plotly chart HTML embeds inline <script> blocks (the bundled plotly.js plus
# the Plotly.newPlot call). The global CSP's `script-src 'self'` blocks inline
# execution, leaving every chart iframe blank. Relax CSP only for the HTML chart
# files we generate ourselves — they are sandboxed in an iframe and never carry
# user-authored markup. PNG/other files keep the strict global policy.
_CHART_HTML_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.plot.ly; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; "
    "font-src 'self' data:; "
    "connect-src 'self'; "
    "frame-ancestors 'self'; "
    "object-src 'none'; "
    "base-uri 'self'"
)


def _chart_headers(filename: str) -> dict[str, str]:
    # SecurityHeadersMiddleware uses setdefault, so an explicit CSP here wins.
    return {"Content-Security-Policy": _CHART_HTML_CSP} if filename.endswith(".html") else {}


# Serve charts: DB first, fallback to tmp/ on disk
@app.get("/files/{filename:path}")
async def serve_file(filename: str, db: AsyncSession = Depends(get_db)):
    """Serve chart files from database (web_charts table), falling back to disk."""
    from models import WebChart
    result = await db.execute(select(WebChart).where(WebChart.filename == filename))
    chart = result.scalar_one_or_none()
    headers = _chart_headers(filename)
    if chart:
        return Response(content=chart.data, media_type=chart.content_type, headers=headers)
    # Fallback to filesystem for backward compatibility with existing files.
    # Resolve and require containment within TMP_DIR to block path-traversal escapes.
    tmp_root = TMP_DIR.resolve()
    filepath = (tmp_root / filename).resolve()
    if filepath.is_relative_to(tmp_root) and filepath.exists():
        return FileResponse(str(filepath), headers=headers)
    raise HTTPException(status_code=404, detail="File not found")

# Serve frontend static files in production (catch-all, must be last)
frontend_dist = Path(__file__).parent.parent / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")
