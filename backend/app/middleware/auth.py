"""JWT authentication middleware for GSIP.

Verifies Supabase-issued JWTs (HS256, symmetric secret).
When ENABLE_AUTH=false the middleware is a no-op and every request is treated
as an anonymous viewer — useful for local dev without Supabase configured.

Token claims we read:
  sub           → user UUID (Supabase user ID)
  email         → user e-mail
  app_metadata  → dict that must contain "role" set by the service-role key
                  (viewer | ministry_maker | ministry_checker | admin)
  aud           → must equal "authenticated" (Supabase default)
"""

import logging
from dataclasses import dataclass, field
from typing import Literal

from fastapi import HTTPException, Request, status
from jose import ExpiredSignatureError, JWTError, jwt

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


def _decode_token(token: str) -> AuthUser:
    """Decode and validate a Supabase JWT.  Raises HTTPException on any failure."""
    if not settings.supabase_jwt_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Auth service not configured (SUPABASE_JWT_SECRET missing)",
        )

    try:
        claims: dict = jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
            audience="authenticated",
            options={"verify_exp": True},
        )
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

    user_id: str = claims.get("sub", "")
    email: str = claims.get("email", "")
    app_meta: dict = claims.get("app_metadata", {})
    role_raw: str = app_meta.get("role", "viewer")

    # Sanitise role — unknown roles get downgraded to viewer
    if role_raw not in ROLE_HIERARCHY:
        logger.warning("Unknown role %r for user %s — defaulting to viewer", role_raw, user_id)
        role_raw = "viewer"

    return AuthUser(
        user_id=user_id,
        email=email,
        role=role_raw,  # type: ignore[arg-type]
        raw_claims=claims,
    )


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
        # Dev mode: treat all requests as admin so nothing is blocked
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
    """FastAPI dependency — returns user if a valid token is present, else None.

    Use this on public-read endpoints where auth enhances the response but
    isn't strictly required (e.g., layer listing, health checks).
    """
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
