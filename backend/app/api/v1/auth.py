"""Auth endpoints — identity and role management.

These endpoints are thin wrappers; the heavy lifting (JWT issuance, OAuth,
email confirmation) is all handled by Supabase on the client side.
The backend only needs to:
  1. Confirm who the caller is (/me)
  2. Let admins assign roles via the Supabase service-role key (/roles/assign)
"""

import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, status

from app.config import settings
from app.middleware.auth import AuthUser, get_current_user, require_admin
from app.schemas.auth import RoleAssignRequest, RoleAssignResponse, UserRead

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/me", response_model=UserRead, summary="Get current user identity")
async def get_me(user: AuthUser = Depends(get_current_user)) -> UserRead:
    """Return the authenticated caller's identity and role.

    Useful for the frontend to know which UI elements to show/hide.
    Returns 401 when called without a valid Bearer token.
    """
    return UserRead(user_id=user.user_id, email=user.email, role=user.role)


@router.post(
    "/roles/assign",
    response_model=RoleAssignResponse,
    summary="Assign a role to a user (admin only)",
    dependencies=[Depends(require_admin)],
)
async def assign_role(payload: RoleAssignRequest) -> RoleAssignResponse:
    """Set app_metadata.role for a Supabase user via the service-role key.

    Requires admin role.  Role is persisted in Supabase and will appear in
    the user's next JWT (after token refresh).

    Valid roles: viewer, ministry_maker, ministry_checker, admin
    """
    from app.middleware.auth import ROLE_HIERARCHY

    if payload.role not in ROLE_HIERARCHY:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid role '{payload.role}'. Valid roles: {list(ROLE_HIERARCHY.keys())}",
        )

    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Supabase service-role key not configured",
        )

    # Supabase Admin API: update user's app_metadata
    url = f"{settings.supabase_url}/auth/v1/admin/users/{payload.user_id}"
    headers = {
        "apikey": settings.supabase_service_role_key,
        "Authorization": f"Bearer {settings.supabase_service_role_key}",
        "Content-Type": "application/json",
    }
    body = {"app_metadata": {"role": payload.role}}

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.put(url, json=body, headers=headers)

    if resp.status_code not in (200, 204):
        logger.error("Supabase role assign failed: %s — %s", resp.status_code, resp.text)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to update role in Supabase",
        )

    logger.info("Role '%s' assigned to user %s", payload.role, payload.user_id)
    return RoleAssignResponse(user_id=payload.user_id, role=payload.role, updated=True)
