"""Azure App Service EasyAuth — header-based user authentication.

Azure AD authentication is handled at the infrastructure level by Azure App Service.
By the time a request reaches this app, Azure has already validated the user and
injected the identity into the X-MS-CLIENT-PRINCIPAL-NAME header.

For WebSocket upgrades with custom OIDC providers (e.g. Okta), Azure does not
always inject those headers — see ``_user_from_easyauth_session`` for the
cookie-based fallback used in that case.

When DEV_MODE=true, authentication is bypassed with a mock dev user.

Okta first-name lookup
----------------------
If ``OKTA_USERINFO_ENDPOINT`` is set (e.g. ``https://adobe.okta.com/oauth2/v1/userinfo``),
the backend calls that endpoint with the user's access token to fetch ``given_name``
(the user's real first name) and stores it as ``display_name`` in the DB.

  HTTP path  : reads the access token from the ``X-MS-TOKEN-OKTA-ACCESS-TOKEN``
               header that Azure EasyAuth injects when Token Store is enabled
               (header name = X-MS-TOKEN-{PROVIDER_NAME}-ACCESS-TOKEN, provider is "okta").
  WebSocket  : extracts the access token from the ``/.auth/me`` payload (already
               fetched for the session-cookie fallback).

Results are cached per access-token for 1 hour to avoid hitting Okta on every request.
"""

import hashlib
import hmac
import logging
import os
import time
import uuid

import httpx
from fastapi import Depends, HTTPException, Request, WebSocket
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

from config import DEV_MODE, TEST_USER_EMAIL
from database import get_db
from models import WebUser

# Bot shared-secret token. Loaded once at import; rotation requires a process
# restart, the same trade-off as every other env-driven secret in the backend.
BOT_SHARED_TOKEN = os.getenv("RTB_BOT_SHARED_TOKEN", "")

# Okta userinfo endpoint — set to enable first-name lookup.
# e.g. "https://adobe.okta.com/oauth2/v1/userinfo"
OKTA_USERINFO_ENDPOINT = os.getenv("OKTA_USERINFO_ENDPOINT", "")

# Simple in-memory cache: access_token -> (first_name, expiry_timestamp)
_okta_cache: dict[str, tuple[str, float]] = {}
_OKTA_CACHE_TTL = 3600  # 1 hour


async def _get_okta_first_name(access_token: str) -> str | None:
    """Call the Okta userinfo endpoint and return the user's first name (given_name).

    Returns None if OKTA_USERINFO_ENDPOINT is not configured, the call fails,
    or the response has no given_name field.  Results are cached per token for
    1 hour so we don't hit Okta on every request.
    """
    if not OKTA_USERINFO_ENDPOINT or not access_token:
        return None

    now = time.monotonic()
    cached = _okta_cache.get(access_token)
    if cached and cached[1] > now:
        return cached[0]

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(
                OKTA_USERINFO_ENDPOINT,
                headers={"Authorization": f"Bearer {access_token}"},
            )
        r.raise_for_status()
        first_name = r.json().get("given_name")
    except Exception as exc:
        logger.warning("Okta userinfo lookup failed: %s", exc)
        return None

    if first_name:
        _okta_cache[access_token] = (first_name, now + _OKTA_CACHE_TTL)
    return first_name or None


# --- Dev mode mock user ---
_DEV_USER = WebUser(
    id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
    azure_ad_oid="dev-user",
    email=TEST_USER_EMAIL,
    display_name="Dev User",
)


def _email_to_oid(email: str) -> str:
    """Derive a stable OID from an email address (used when no explicit OID header)."""
    return hashlib.sha256(email.encode()).hexdigest()[:32]


def _email_to_display_name(email: str) -> str | None:
    """Best-effort first/last from the local-part: 'jane.doe@x' -> 'Jane Doe'."""
    if email and "@" in email:
        return email.split("@")[0].replace(".", " ").title()
    return None


async def get_or_create_user(
    db: AsyncSession,
    oid: str,
    email: str,
    display_name: str | None = None,
    okta_name: str | None = None,
) -> WebUser:
    """Find existing user by Azure AD OID, or create a new one.

    ``display_name`` is used only on first creation (best available name from
    Okta → header → email fallback chain).  For existing users, only ``okta_name``
    triggers a DB update — fallback names never overwrite a stored value, which
    prevents oscillation when the Okta token is transiently unavailable.
    """
    result = await db.execute(select(WebUser).where(WebUser.azure_ad_oid == oid))
    user = result.scalar_one_or_none()
    if user is None:
        user = WebUser(azure_ad_oid=oid, email=email, display_name=display_name)
        db.add(user)
        await db.flush()
    elif okta_name and user.display_name != okta_name:
        user.display_name = okta_name
    return user


async def _user_from_headers(headers, db: AsyncSession) -> WebUser:
    """Extract user identity from Azure EasyAuth headers."""
    email = headers.get("X-MS-CLIENT-PRINCIPAL-NAME")
    if not email:
        raise HTTPException(status_code=401, detail="Not authenticated — missing X-MS-CLIENT-PRINCIPAL-NAME header")

    oid = headers.get("X-MS-CLIENT-PRINCIPAL-ID") or _email_to_oid(email)

    # Try Okta userinfo first (requires Token Store enabled in Azure EasyAuth so that
    # the access token is injected as X-MS-TOKEN-OKTA-ACCESS-TOKEN).
    access_token = headers.get("X-MS-TOKEN-OKTA-ACCESS-TOKEN", "")
    okta_name = await _get_okta_first_name(access_token)

    # Build display_name for first-time creation: Okta → header → email fallback.
    display_name = (
        okta_name
        or headers.get("X-MS-CLIENT-PRINCIPAL-DISPLAY-NAME")
        or _email_to_display_name(email)
    )
    return await get_or_create_user(db, oid, email, display_name, okta_name=okta_name)


def _has_bot_token(headers) -> bool:
    """Did the caller present an X-Bot-Token header?

    Used to switch the auth path BEFORE token validation: if a bot token is
    present we commit to the bot path end-to-end and 401 on bad token rather
    than silently falling through to EasyAuth (which would surface a confusing
    'missing X-MS-CLIENT-PRINCIPAL-NAME' error to bot operators).
    """
    return bool(headers.get("X-Bot-Token"))


async def _user_from_bot_headers(headers, db: AsyncSession) -> WebUser:
    """Resolve a WebUser from the bot's shared-token + identity headers.

    The bot has already authenticated the end user via Slack/Teams OAuth; the
    backend's job here is only to (a) verify the bot itself and (b) impersonate
    the named end user. Caller must have already checked ``_has_bot_token``.
    """
    token = headers.get("X-Bot-Token") or ""
    if not BOT_SHARED_TOKEN or not hmac.compare_digest(token, BOT_SHARED_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid bot token")
    email = headers.get("X-Bot-User-Email")
    if not email:
        raise HTTPException(status_code=401, detail="Bot request missing X-Bot-User-Email")
    display_name = headers.get("X-Bot-User-Display-Name") or _email_to_display_name(email)
    oid = _email_to_oid(email)
    return await get_or_create_user(db, oid, email, display_name)


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> WebUser:
    """FastAPI dependency: extract user from EasyAuth headers, or from a bot token."""
    if DEV_MODE:
        return _DEV_USER

    if _has_bot_token(request.headers):
        return await _user_from_bot_headers(request.headers, db)
    return await _user_from_headers(request.headers, db)


async def _user_from_easyauth_session(websocket: WebSocket, db: AsyncSession) -> WebUser:
    """Validate a WebSocket via the EasyAuth session cookie by calling /.auth/me.

    Azure App Service EasyAuth reliably injects X-MS-CLIENT-PRINCIPAL-* headers
    on HTTP requests, but with custom OIDC providers (e.g. Okta) those headers
    are often absent on WebSocket upgrade requests. The AppServiceAuthSession
    cookie is still present, so we exchange it for the user's claims by
    calling /.auth/me server-side.
    """
    cookie = websocket.headers.get("cookie", "")
    if "AppServiceAuthSession" not in cookie:
        raise HTTPException(status_code=401, detail="No EasyAuth session cookie on WebSocket")

    hostname = os.getenv("WEBSITE_HOSTNAME")
    if not hostname:
        raise HTTPException(status_code=500, detail="WEBSITE_HOSTNAME env var not set")

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            r = await client.get(f"https://{hostname}/.auth/me", headers={"Cookie": cookie})
        except httpx.HTTPError as e:
            logger.warning("EasyAuth /.auth/me call failed: %s", e)
            raise HTTPException(status_code=502, detail="EasyAuth lookup failed")

    if r.status_code != 200:
        raise HTTPException(status_code=401, detail=f"EasyAuth session invalid ({r.status_code})")

    payload = r.json()
    if not payload:
        raise HTTPException(status_code=401, detail="No identity in EasyAuth response")

    user_data = payload[0]
    claims = {c["typ"]: c["val"] for c in user_data.get("user_claims", [])}
    email = (
        claims.get("preferred_username")
        or claims.get("http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress")
        or user_data.get("user_id")
    )
    if not email:
        raise HTTPException(status_code=401, detail="No email claim in EasyAuth response")

    oid = (
        claims.get("http://schemas.xmlsoap.org/ws/2005/05/identity/claims/nameidentifier")
        or _email_to_oid(email)
    )

    # Try Okta userinfo using the access token from the /.auth/me payload.
    access_token = user_data.get("access_token", "")
    okta_name = await _get_okta_first_name(access_token)

    # Build display_name for first-time creation: Okta → name claim → email fallback.
    display_name = okta_name or claims.get("name") or _email_to_display_name(email)
    return await get_or_create_user(db, oid, email, display_name, okta_name=okta_name)


async def get_user_from_ws_token(websocket: WebSocket, db: AsyncSession) -> WebUser:
    """Extract user from WebSocket connection.

    EasyAuth headers are reliable on HTTP but not on WebSocket upgrades with
    custom OIDC providers, so we fall back to validating the session cookie
    via /.auth/me when the named headers are absent.
    """
    if DEV_MODE:
        return _DEV_USER

    try:
        if _has_bot_token(websocket.headers):
            return await _user_from_bot_headers(websocket.headers, db)
        if websocket.headers.get("X-MS-CLIENT-PRINCIPAL-NAME"):
            return await _user_from_headers(websocket.headers, db)
        return await _user_from_easyauth_session(websocket, db)
    except HTTPException:
        await websocket.close(code=4001, reason="Not authenticated")
        raise
