"""Tests for the authentication middleware and RBAC logic.

These tests run without a real Supabase project — JWTs are signed with a
test secret so the full verification path is exercised without network calls.
"""

import time

import pytest
from fastapi import HTTPException
from jose import jwt

from app.middleware.auth import (
    ROLE_HIERARCHY,
    AuthUser,
    _decode_token,
    get_current_user,
    get_optional_user,
    require_role,
)


# ─── Helpers ──────────────────────────────────────────────────────────────────

TEST_SECRET = "test-jwt-secret-at-least-32-characters-long"
TEST_USER_ID = "user-uuid-1234"
TEST_EMAIL = "planner@gsip.gov.in"


def _make_token(
    role: str = "viewer",
    expired: bool = False,
    secret: str = TEST_SECRET,
    aud: str = "authenticated",
) -> str:
    """Mint a test JWT signed with TEST_SECRET."""
    now = int(time.time())
    payload = {
        "sub": TEST_USER_ID,
        "email": TEST_EMAIL,
        "aud": aud,
        "iat": now - 60,
        "exp": (now - 10) if expired else (now + 3600),
        "app_metadata": {"role": role},
    }
    return jwt.encode(payload, secret, algorithm="HS256")


class _FakeRequest:
    """Minimal stand-in for a FastAPI Request with Authorization header."""

    def __init__(self, token: str | None = None) -> None:
        self.headers = {}
        if token:
            self.headers["Authorization"] = f"Bearer {token}"


# ─── AuthUser helpers ─────────────────────────────────────────────────────────

def test_auth_user_has_role_exact() -> None:
    """User with role X satisfies has_role(X)."""
    user = AuthUser(user_id="u1", email="a@b.com", role="ministry_maker")
    assert user.has_role("ministry_maker")


def test_auth_user_has_role_higher() -> None:
    """Admin satisfies every role check."""
    user = AuthUser(user_id="u1", email="a@b.com", role="admin")
    for role in ROLE_HIERARCHY:
        assert user.has_role(role)  # type: ignore[arg-type]


def test_auth_user_has_role_lower() -> None:
    """Viewer does not satisfy ministry_maker."""
    user = AuthUser(user_id="u1", email="a@b.com", role="viewer")
    assert not user.has_role("ministry_maker")


# ─── Token decoding ───────────────────────────────────────────────────────────

def test_decode_valid_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Valid token is decoded and returns correct AuthUser."""
    monkeypatch.setattr("app.middleware.auth.settings.supabase_jwt_secret", TEST_SECRET)
    token = _make_token(role="ministry_checker")
    user = _decode_token(token)
    assert user.user_id == TEST_USER_ID
    assert user.email == TEST_EMAIL
    assert user.role == "ministry_checker"


def test_decode_expired_token_raises_401(monkeypatch: pytest.MonkeyPatch) -> None:
    """Expired token must raise 401."""
    monkeypatch.setattr("app.middleware.auth.settings.supabase_jwt_secret", TEST_SECRET)
    token = _make_token(expired=True)
    with pytest.raises(HTTPException) as exc_info:
        _decode_token(token)
    assert exc_info.value.status_code == 401
    assert "expired" in exc_info.value.detail.lower()


def test_decode_wrong_secret_raises_401(monkeypatch: pytest.MonkeyPatch) -> None:
    """Token signed with wrong secret must raise 401."""
    monkeypatch.setattr("app.middleware.auth.settings.supabase_jwt_secret", TEST_SECRET)
    token = _make_token(secret="completely-different-secret-32chars")
    with pytest.raises(HTTPException) as exc_info:
        _decode_token(token)
    assert exc_info.value.status_code == 401


def test_decode_wrong_audience_raises_401(monkeypatch: pytest.MonkeyPatch) -> None:
    """Token with wrong audience must raise 401."""
    monkeypatch.setattr("app.middleware.auth.settings.supabase_jwt_secret", TEST_SECRET)
    token = _make_token(aud="service_role")
    with pytest.raises(HTTPException) as exc_info:
        _decode_token(token)
    assert exc_info.value.status_code == 401


def test_decode_unknown_role_defaults_to_viewer(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unknown role in app_metadata is downgraded to viewer."""
    monkeypatch.setattr("app.middleware.auth.settings.supabase_jwt_secret", TEST_SECRET)
    token = _make_token(role="superuser_xyz")
    user = _decode_token(token)
    assert user.role == "viewer"


def test_decode_missing_jwt_secret_raises_503(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing JWT secret must raise 503 (misconfigured, not 401)."""
    monkeypatch.setattr("app.middleware.auth.settings.supabase_jwt_secret", "")
    token = _make_token()
    with pytest.raises(HTTPException) as exc_info:
        _decode_token(token)
    assert exc_info.value.status_code == 503


# ─── get_current_user dependency ──────────────────────────────────────────────

def test_get_current_user_dev_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """In dev mode (ENABLE_AUTH=false) returns synthetic admin without a token."""
    monkeypatch.setattr("app.middleware.auth.settings.enable_auth", False)
    request = _FakeRequest()
    user = get_current_user(request)
    assert user.role == "admin"
    assert user.user_id == "dev-user"


def test_get_current_user_valid_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Valid token returns the authenticated user."""
    monkeypatch.setattr("app.middleware.auth.settings.enable_auth", True)
    monkeypatch.setattr("app.middleware.auth.settings.supabase_jwt_secret", TEST_SECRET)
    token = _make_token(role="admin")
    request = _FakeRequest(token=token)
    user = get_current_user(request)
    assert user.role == "admin"
    assert user.email == TEST_EMAIL


def test_get_current_user_no_token_raises_401(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing Authorization header must raise 401 when auth is enabled."""
    monkeypatch.setattr("app.middleware.auth.settings.enable_auth", True)
    request = _FakeRequest()
    with pytest.raises(HTTPException) as exc_info:
        get_current_user(request)
    assert exc_info.value.status_code == 401


# ─── get_optional_user dependency ────────────────────────────────────────────

def test_get_optional_user_no_token_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """No token → None (not an error) for optional-auth endpoints."""
    monkeypatch.setattr("app.middleware.auth.settings.enable_auth", True)
    request = _FakeRequest()
    user = get_optional_user(request)
    assert user is None


def test_get_optional_user_valid_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Valid token → AuthUser for optional-auth endpoints."""
    monkeypatch.setattr("app.middleware.auth.settings.enable_auth", True)
    monkeypatch.setattr("app.middleware.auth.settings.supabase_jwt_secret", TEST_SECRET)
    token = _make_token(role="viewer")
    request = _FakeRequest(token=token)
    user = get_optional_user(request)
    assert user is not None
    assert user.role == "viewer"


# ─── require_role factory ────────────────────────────────────────────────────

def test_require_role_passes_for_sufficient_role(monkeypatch: pytest.MonkeyPatch) -> None:
    """require_role('ministry_maker') passes for an admin user."""
    monkeypatch.setattr("app.middleware.auth.settings.enable_auth", True)
    monkeypatch.setattr("app.middleware.auth.settings.supabase_jwt_secret", TEST_SECRET)
    token = _make_token(role="admin")
    request = _FakeRequest(token=token)
    dep = require_role("ministry_maker")
    user = dep(request)
    assert user.role == "admin"


def test_require_role_raises_403_for_insufficient_role(monkeypatch: pytest.MonkeyPatch) -> None:
    """require_role('admin') raises 403 for a viewer."""
    monkeypatch.setattr("app.middleware.auth.settings.enable_auth", True)
    monkeypatch.setattr("app.middleware.auth.settings.supabase_jwt_secret", TEST_SECRET)
    token = _make_token(role="viewer")
    request = _FakeRequest(token=token)
    dep = require_role("admin")
    with pytest.raises(HTTPException) as exc_info:
        dep(request)
    assert exc_info.value.status_code == 403
    assert "admin" in exc_info.value.detail


# ─── Role hierarchy coverage ─────────────────────────────────────────────────

def test_role_hierarchy_completeness() -> None:
    """All expected roles are present in ROLE_HIERARCHY."""
    expected = {"viewer", "ministry_maker", "ministry_checker", "admin"}
    assert expected == set(ROLE_HIERARCHY.keys())


def test_role_hierarchy_ordering() -> None:
    """admin > checker > maker > viewer."""
    assert ROLE_HIERARCHY["admin"] > ROLE_HIERARCHY["ministry_checker"]
    assert ROLE_HIERARCHY["ministry_checker"] > ROLE_HIERARCHY["ministry_maker"]
    assert ROLE_HIERARCHY["ministry_maker"] > ROLE_HIERARCHY["viewer"]
