"""TradingWorkstation login gate tests."""

from pathlib import Path

from gridtrade.api.tw_auth import TwAuthStore, safe_next


def make_store(tmp_path: Path) -> TwAuthStore:
    return TwAuthStore(
        tmp_path / "tw_auth.db",
        ["040418jie@gmail.com", "jacklika.business@gmail.com"],
    )


def test_allowed_email_password_and_session(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    assert store.allowed_email("040418JIE@gmail.com") is True
    assert store.allowed_email("other@gmail.com") is False
    assert store.has_password("040418jie@gmail.com") is False
    assert store.verify("040418jie@gmail.com", "whatever") is False

    store.set_password("040418jie@gmail.com", "TestPass123")
    assert store.has_password("040418jie@gmail.com") is True
    assert store.verify("040418jie@gmail.com", "TestPass123") is True
    assert store.verify("040418jie@gmail.com", "wrong") is False

    token = store.create_session("040418jie@gmail.com")
    assert store.session_email(token) == "040418jie@gmail.com"
    store.revoke(token)
    assert store.session_email(token) is None


def test_pending_and_one_time_codes(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    pending = store.create_pending("jacklika.business@gmail.com", "/TradingWorkstation")
    assert store.consume_pending(pending) == ("jacklika.business@gmail.com", "/TradingWorkstation")
    assert store.consume_pending(pending) is None

    code = store.create_code("jacklika.business@gmail.com", "/TradingWorkstation")
    assert store.consume_code(code) == ("jacklika.business@gmail.com", "/TradingWorkstation")
    assert store.consume_code(code) is None


def test_pending_peek_is_non_destructive(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    token = store.create_pending("040418jie@gmail.com", "/TradingWorkstation")
    assert store.peek_pending(token) == ("040418jie@gmail.com", "/TradingWorkstation")
    assert store.peek_pending(token) == ("040418jie@gmail.com", "/TradingWorkstation")
    assert store.consume_pending(token) is not None
    assert store.peek_pending(token) is None


def test_safe_next_rejects_absolute_and_protocol_relative() -> None:
    assert safe_next("/TradingWorkstation") == "/TradingWorkstation"
    assert safe_next("https://evil.example") == "/TradingWorkstation"
    assert safe_next("//evil.example") == "/TradingWorkstation"


def test_change_password(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.set_password("040418jie@gmail.com", "OldPass123")
    assert store.change_password("040418jie@gmail.com", "wrong", "NewPass123") is False
    assert store.verify("040418jie@gmail.com", "OldPass123") is True
    assert store.change_password("040418jie@gmail.com", "OldPass123", "NewPass123") is True
    assert store.verify("040418jie@gmail.com", "OldPass123") is False
    assert store.verify("040418jie@gmail.com", "NewPass123") is True
