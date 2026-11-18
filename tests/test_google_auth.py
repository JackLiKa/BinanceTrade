"""Google device-flow auth, allowlist and session tests (no network)."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from gridtrade.api.admin import AdminAuth
from urllib.parse import parse_qs, urlparse

from gridtrade.api.google_auth import (
    DEVICE_CODE_URL,
    TOKEN_URL,
    USERINFO_URL,
    GoogleAuthError,
    GoogleAuthStore,
    GoogleDeviceFlow,
    GoogleWebError,
    GoogleWebOAuth,
)


def make_handler(*, email="user@example.com", email_verified=True, first_pending=True):
    state = {"token_calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == DEVICE_CODE_URL:
            return httpx.Response(
                200,
                json={
                    "device_code": "device-abc",
                    "user_code": "ABCD-EFGH",
                    "verification_url": "https://www.google.com/device",
                    "expires_in": 1800,
                    "interval": 5,
                },
            )
        if str(request.url) == TOKEN_URL:
            state["token_calls"] += 1
            if first_pending and state["token_calls"] == 1:
                return httpx.Response(400, json={"error": "authorization_pending"})
            return httpx.Response(200, json={"access_token": "access-xyz", "token_type": "Bearer"})
        if str(request.url) == USERINFO_URL:
            assert request.headers["Authorization"] == "Bearer access-xyz"
            return httpx.Response(
                200,
                json={"email": email, "email_verified": email_verified, "name": "Test User"},
            )
        return httpx.Response(404)

    return handler


def make_flow(tmp_path: Path, **kwargs):
    store = GoogleAuthStore(tmp_path / "auth.db")
    store.set_config(client_id="client-id", client_secret="client-secret", enabled=True)
    client = httpx.Client(transport=httpx.MockTransport(make_handler(**kwargs)))
    return store, GoogleDeviceFlow(store, client)


def test_allowlist_and_sessions(tmp_path: Path) -> None:
    store = GoogleAuthStore(tmp_path / "auth.db")
    store.set_config(client_id="id", client_secret="secret", enabled=True)

    with pytest.raises(ValueError):
        store.add_user("not-an-email")
    store.add_user("User@Example.com", "User")
    assert store.is_allowed("user@example.com")

    token = store.create_session("user@example.com")
    assert store.session_email(token) == "user@example.com"
    store.revoke_session(token)
    assert store.session_email(token) is None

    # Removing the allowlisted user invalidates existing sessions.
    token = store.create_session("user@example.com")
    assert store.remove_user("user@example.com") is True
    assert store.session_email(token) is None


def test_device_flow_pending_then_login(tmp_path: Path) -> None:
    store, flow = make_flow(tmp_path)
    store.add_user("user@example.com", "User")

    started = flow.start()
    assert started["user_code"] == "ABCD-EFGH"
    assert started["verification_url"] == "https://www.google.com/device"

    pending = flow.poll(started["flow_id"])
    assert pending["status"] == "pending"

    result = flow.poll(started["flow_id"])
    assert result["status"] == "ok"
    assert result["email"] == "user@example.com"
    token = result["session_token"]
    assert store.session_email(token) == "user@example.com"

    # Repeated poll returns the same completed state, not a new session.
    again = flow.poll(started["flow_id"])
    assert again["status"] == "ok"
    assert again["session_token"] == token


def test_device_flow_rejects_unknown_email(tmp_path: Path) -> None:
    store, flow = make_flow(tmp_path)
    started = flow.start()
    flow.poll(started["flow_id"])  # authorization_pending
    result = flow.poll(started["flow_id"])
    assert result["status"] == "not_allowed"
    assert result["email"] == "user@example.com"
    assert store.create_session("user@example.com")  # sessions can exist, but not allowed
    assert store.session_email(store.create_session("user@example.com")) is None


def test_device_flow_requires_config(tmp_path: Path) -> None:
    store = GoogleAuthStore(tmp_path / "auth.db")
    flow = GoogleDeviceFlow(store, httpx.Client(transport=httpx.MockTransport(make_handler())))
    with pytest.raises(GoogleAuthError):
        flow.start()


def test_unverified_email_is_rejected(tmp_path: Path) -> None:
    store, flow = make_flow(tmp_path, email_verified=False)
    store.add_user("user@example.com")
    started = flow.start()
    flow.poll(started["flow_id"])  # pending
    result = flow.poll(started["flow_id"])
    assert result["status"] == "error"
    assert "验证" in result["error"]


def test_admin_flag_and_google_admin_session(tmp_path: Path) -> None:
    store = GoogleAuthStore(tmp_path / "auth.db")
    store.add_user("Admin@Example.com", "Admin", "admin", is_admin=True)
    assert store.is_admin("admin@example.com") is True
    assert store.is_allowed("admin@example.com") is True
    store.set_admin("admin@example.com", False)
    assert store.is_admin("admin@example.com") is False

    auth = AdminAuth(tmp_path / "admin.db")
    token = auth.grant("admin@example.com")
    assert auth.check(token) is True
    auth.logout(token)
    assert auth.check(token) is False


def test_web_oauth_start_and_exchange(tmp_path: Path) -> None:
    store = GoogleAuthStore(tmp_path / "auth.db")
    store.set_web_config(client_id="web-client", client_secret="web-secret")
    store.add_user("web@example.com")

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == TOKEN_URL:
            return httpx.Response(200, json={"access_token": "web-token"})
        if str(request.url) == USERINFO_URL:
            return httpx.Response(200, json={"email": "web@example.com", "email_verified": True})
        return httpx.Response(404)

    flow = GoogleWebOAuth(store, httpx.Client(transport=httpx.MockTransport(handler)))
    url = flow.start(redirect_uri="https://gt.example.com/api/auth/google/callback", purpose="panel", next_path="/", app=True)
    query = parse_qs(urlparse(url).query)
    assert query["client_id"] == ["web-client"]
    assert query["redirect_uri"] == ["https://gt.example.com/api/auth/google/callback"]
    assert query["prompt"] == ["select_account"]
    state = query["state"][0]
    result = flow.exchange("code-1", state)
    assert result["email"] == "web@example.com"
    assert result["app"] is True
    assert result["next"] == "/"
    with pytest.raises(GoogleWebError):
        flow.exchange("code-1", state)


def test_one_time_app_codes_are_single_use(tmp_path: Path) -> None:
    store = GoogleAuthStore(tmp_path / "auth.db")
    store.add_user("app@example.com")
    code = store.create_code("app@example.com")
    assert store.consume_code(code) == "app@example.com"
    assert store.consume_code(code) is None
    assert store.consume_code("missing") is None
