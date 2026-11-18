"""Google device-flow auth, allowlist and session tests (no network)."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from gridtrade.api.google_auth import (
    DEVICE_CODE_URL,
    TOKEN_URL,
    USERINFO_URL,
    GoogleAuthError,
    GoogleAuthStore,
    GoogleDeviceFlow,
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
