"""Pydantic schemas for authentication responses."""

from pydantic import BaseModel, EmailStr


class UserRead(BaseModel):
    """Public user representation returned from /auth/me."""

    user_id: str
    email: str
    role: str

    model_config = {"from_attributes": True}


class RoleAssignRequest(BaseModel):
    """Request body for assigning a role to a user (admin only)."""

    user_id: str
    role: str


class RoleAssignResponse(BaseModel):
    """Confirmation of a role assignment."""

    user_id: str
    role: str
    updated: bool
