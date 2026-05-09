"""JWT authentication middleware for GSIP.

Supports both Supabase token flavours:
  ES256 (EC P-256) — all new Supabase projects (2024+).  Public key is fetched
                      once from the JWKS endpoint and cached in memory.
  HS256 (symmetric) — older projects or local test tokens.  Uses SUPABASE_JWT_SECRET.

The algorithm is read from the token header so old and new projects work without
any config change.

When ENABLE_AUTH=false the middleware is a no-op — every request is treated as
an anonymous admin (useful for local dev without Supabase configured).

Token claims we read:
  sub           → user UUID (Supabase user ID)
  email         → user e-mail
  app_metadata  → dict that must contain "role" set by the service-role key
                  (viewer | ministry_maker | ministry_checker | admin)
  aud           → must equal "authenticated"
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Literal

import httpx
from fastapi import HTTPException, Request, status
from jose import ExpiredSignatureError, JWTError, jwk, jwt

from app.config import settings

logger = logging.getLogger(__name__)

# Role hierarchy — higher index = higher privilege
ROLE_HIERARCHY: dict[str, int] = {
    "viewer": 0,
    "ministry_maker": 1,
    "ministry_checker": 2,
    "admin": 3,
}

RoleType = Literal["viewer", "ministry_maker", "ministry_checker", "admin"]

# ── JWKS cache ────────────────────────────────────────────────────────────────
# Keyed by kid → JWK dict.  Refreshed at most once every 24 hours.

_JWKS_CACHE: dict[str, dict] = {}
_JWKS_LOCK = threading.Lock()
_JWKS_FETCHED_AT: float = 0.0
_JWKS_TTL = 86_400  # 24 hours


def _fetch_jwks() -> None:
    """Fetch Supabase JWKS and populate _JWKS_CACHE.  Called at most once/day."""
    global _JWKS_FETCHED_AT
    if not settings.supabase_url:
        return
    url = f"{settings.supabase_url}/auth/v1/.well-known/jwks.json"
    try:
        resp = httpx.get(url, timeout=10.0)
        resp.raise_for_status()
        data = resp.json()
        for key in data.get("keys", []):
            kid = key.get("kid")
            if kid:
                _JWKS_CACHE[kid] = key
        _JWKS_FETCHED_AT = time.monotonic()
        logger.info("JWKS loaded: %d key(s) cached", len(_JWKS_CACHE))
    except Exception as exc:
        logger.warning("Failed to fetch JWKS from %s: %s", url, exc)


def _get_jwks_key(kid: str) -> dict | None:
    """Return the cached JWK for `kid`, refreshing if stale or missing."""
    with _JWKS_LOCK:
        staleness = time.monotonic() - _JWKS_FETCHED_AT
        if staleness > _JWKS_TTL or kid not in _JWKS_CACHE:
            _fetch_jwks()
        return _JWKS_CACHE.get(kid)


# ── AuthUser ─────────────────────────────────────────────────────────────────

@dataclass
class AuthUser:
    """Authenticated user extracted from the Supabase JWT."""

    user_id: str
    email: str
    role: RoleType = "viewer"
    raw_claims: dict = field(default_factory=dict)

    def has_role(self, minimum_role: RoleType) -> bool:
        """Return True if this user's role is >= minimum_role in the hierarchy."""
        return ROLE_HIERARCHY.get(self.role, 0) >= ROLE_HIERARCHY.get(minimum_role, 0)


# ── Token decoding ────────────────────────────────────────────────────────────

def _decode_token(token: str) -> AuthUser:
    """Decode and validate a Supabase JWT.  Raises HTTPException on any failure.

    Supports ES256 (JWKS) and HS256 (symmetric secret) automatically.
    """
    # Peek at the header to pick the right verification strategy
    try:
        header = jwt.get_unverified_header(token)
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    alg = header.get("alg", "HS256")

    try:
        if alg == "ES256":
            claims = _decode_es256(token, header)
        else:
            claims = _decode_hs256(token)
    except ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None
    except JWTError as exc:
        logger.debug("JWT decode failure: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    return _claims_to_user(claims)


def _decode_es256(token: str, header: dict) -> dict:
    """Verify an ES256 Supabase token using the cached JWKS public key."""
    kid = header.get("kid", "")
    jwk_dict = _get_jwks_key(kid)
    if not jwk_dict:
        raise JWTError(f"No JWKS key found for kid={kid!r}")

    public_key = jwk.construct(jwk_dict, algorithm="ES256")
    return jwt.decode(
        token,
        public_key,
        algorithms=["ES256"],
        audience="authenticated",
        options={"verify_exp": True},
    )


def _decode_hs256(token: str) -> dict:
    """Verify an HS256 token using the configured JWT secret (tests / old projects)."""
    if not settings.supabase_jwt_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Auth service not configured (SUPABASE_JWT_SECRET missing)",
        )
    return jwt.decode(
        token,
        settings.supabase_jwt_secret,
        algorithms=["HS256"],
        audience="authenticated",
        options={"verify_exp": True},
    )


def _claims_to_user(claims: dict) -> AuthUser:
    """Extract user identity and role from decoded JWT claims."""
    user_id: str = claims.get("sub", "")
    email: str = claims.get("email", "")
    app_meta: dict = claims.get("app_metadata", {})
    role_raw: str = app_meta.get("role", "viewer")

    if role_raw not in ROLE_HIERARCHY:
        logger.warning("Unknown role %r for user %s — defaulting to viewer", role_raw, user_id)
        role_raw = "viewer"

    return AuthUser(
        user_id=user_id,
        email=email,
        role=role_raw,  # type: ignore[arg-type]
        raw_claims=claims,
    )


# ── FastAPI dependencies ──────────────────────────────────────────────────────

def _extract_bearer(request: Request) -> str | None:
    """Pull the Bearer token from the Authorization header, or None."""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:].strip()
    return None


def get_current_user(request: Request) -> AuthUser:
    """FastAPI dependency — returns the authenticated user or raises 401.

    When ENABLE_AUTH=false, returns a synthetic admin user so every endpoint
    works in dev without a real Supabase project.
    """
    if not settings.enable_auth:
        return AuthUser(user_id="dev-user", email="dev@gsip.local", role="admin")

    token = _extract_bearer(request)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return _decode_token(token)


def get_optional_user(request: Request) -> AuthUser | None:
    """FastAPI dependency — returns user if a valid token is present, else None."""
    if not settings.enable_auth:
        return AuthUser(user_id="dev-user", email="dev@gsip.local", role="admin")

    token = _extract_bearer(request)
    if not token:
        return None
    try:
        return _decode_token(token)
    except HTTPException:
        return None


def require_role(minimum_role: RoleType):
    """Factory for a FastAPI dependency that enforces a minimum role.

    Usage:
        @router.post("/layers/publish")
        async def publish_layer(user: AuthUser = Depends(require_role("admin"))):
            ...
    """
    def dependency(request: Request) -> AuthUser:
        user = get_current_user(request)
        if not user.has_role(minimum_role):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires role '{minimum_role}' or higher (you have '{user.role}')",
            )
        return user
    return dependency


# Pre-built role dependencies — import these directly for convenience
require_admin = require_role("admin")
require_checker = require_role("ministry_checker")
require_maker = require_role("ministry_maker")
require_viewer = require_role("viewer")
