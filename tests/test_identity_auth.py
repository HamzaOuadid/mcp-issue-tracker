from __future__ import annotations

import pytest

from mcp_issue_tracker.auth import AuthMiddleware
from mcp_issue_tracker.errors import ErrorCode, MCPError
from mcp_issue_tracker.identity import MockIdentityProvider, User


def test_resolve_known_token_returns_user():
    provider = MockIdentityProvider()
    user = provider.resolve("token-alice")
    assert user.user_id == "alice"
    assert user.team == "engineering"
    assert user.is_admin is False


def test_resolve_unknown_token_returns_none():
    provider = MockIdentityProvider()
    assert provider.resolve("not-a-real-token") is None


def test_resolve_missing_token_returns_none():
    provider = MockIdentityProvider()
    assert provider.resolve(None) is None
    assert provider.resolve("") is None


def test_two_users_are_distinct():
    provider = MockIdentityProvider()
    alice = provider.resolve("token-alice")
    bob = provider.resolve("token-bob")
    assert alice.user_id != bob.user_id
    assert alice.team != bob.team


def test_admin_flag():
    provider = MockIdentityProvider()
    admin = provider.resolve("token-admin")
    assert admin.is_admin is True


def test_auth_middleware_accepts_valid_token():
    mw = AuthMiddleware(MockIdentityProvider())
    user = mw.authenticate("token-bob")
    assert user.user_id == "bob"


def test_auth_middleware_rejects_missing_token():
    mw = AuthMiddleware(MockIdentityProvider())
    with pytest.raises(MCPError) as exc_info:
        mw.authenticate(None)
    assert exc_info.value.code == ErrorCode.UNAUTHENTICATED


def test_auth_middleware_rejects_invalid_token():
    mw = AuthMiddleware(MockIdentityProvider())
    with pytest.raises(MCPError) as exc_info:
        mw.authenticate("garbage-token-12345")
    assert exc_info.value.code == ErrorCode.UNAUTHENTICATED


def test_auth_middleware_never_falls_back_to_default_identity():
    # Registering zero tokens means every call must fail closed, not
    # resolve to some default/anonymous identity.
    mw = AuthMiddleware(MockIdentityProvider(tokens={}))
    with pytest.raises(MCPError):
        mw.authenticate("token-alice")
