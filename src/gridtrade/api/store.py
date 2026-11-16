"""SQLite persistence for research runs, artifacts and the audit trail.

WAL keeps the HTTP handlers from blocking behind a running backtest, and every
call uses its own short-lived connection so jobs on worker threads never share
a connection with the event loop.
"""

from __future__ import annotations

import gzip
import json
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    symbol TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    params TEXT NOT NULL,
    summary TEXT,
    error TEXT,
    progress REAL NOT NULL DEFAULT 0,
    message TEXT NOT NULL DEFAULT '',
    cancel_requested INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS runs_created ON runs(created_at DESC);

CREATE TABLE IF NOT EXISTS artifacts (
    run_id TEXT PRIMARY KEY,
    payload BLOB NOT NULL,
    bytes INTEGER NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    detail TEXT NOT NULL
);
"""

RUN_FIELDS = {
    "status",
    "started_at",
    "finished_at",
    "summary",
    "error",
    "progress",
    "message",
    "cancel_requested",
}


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def new_run_id() -> str:
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + secrets.token_hex(3)


class Store:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self.connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(SCHEMA)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # -- runs -------------------------------------------------------------

    def create_run(self, kind: str, symbol: str, params: dict[str, Any]) -> str:
        run_id = new_run_id()
        with self._lock, self.connect() as conn:
            conn.execute(
                "INSERT INTO runs (id, kind, symbol, status, created_at, params)"
                " VALUES (?, ?, ?, 'queued', ?, ?)",
                (run_id, kind, symbol, utcnow(), json.dumps(params, sort_keys=True)),
            )
        return run_id

    def update_run(self, run_id: str, **fields: Any) -> None:
        unknown = set(fields) - RUN_FIELDS
        if unknown:
            raise ValueError(f"not a run column: {sorted(unknown)}")
        if not fields:
            return
        if "summary" in fields and fields["summary"] is not None and not isinstance(
            fields["summary"], str
        ):
            fields["summary"] = json.dumps(fields["summary"], sort_keys=True)
        assignments = ", ".join(f"{name} = ?" for name in fields)
        with self._lock, self.connect() as conn:
            conn.execute(
                f"UPDATE runs SET {assignments} WHERE id = ?",
                (*fields.values(), run_id),
            )

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        return self._run_dict(row) if row else None

    def list_runs(self, *, limit: int = 30, kind: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM runs"
        args: list[Any] = []
        if kind:
            sql += " WHERE kind = ?"
            args.append(kind)
        sql += " ORDER BY created_at DESC LIMIT ?"
        args.append(max(1, min(int(limit), 200)))
        with self.connect() as conn:
            rows = conn.execute(sql, args).fetchall()
        return [self._run_dict(row) for row in rows]

    def latest_succeeded(self, kind: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM runs WHERE kind = ? AND status = 'succeeded'"
                " ORDER BY finished_at DESC LIMIT 1",
                (kind,),
            ).fetchone()
        return self._run_dict(row) if row else None

    def fail_interrupted(self, message: str) -> int:
        with self._lock, self.connect() as conn:
            cur = conn.execute(
                "UPDATE runs SET status = 'failed', message = ?, finished_at = ?"
                " WHERE status IN ('queued', 'running')",
                (message, utcnow()),
            )
            return cur.rowcount

    def request_cancel(self, run_id: str) -> bool:
        with self._lock, self.connect() as conn:
            cur = conn.execute(
                "UPDATE runs SET cancel_requested = 1"
                " WHERE id = ? AND status IN ('queued', 'running')",
                (run_id,),
            )
            return cur.rowcount > 0

    @staticmethod
    def _run_dict(row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        try:
            data["params"] = json.loads(data["params"])
        except (TypeError, json.JSONDecodeError):
            data["params"] = {}
        if data.get("summary"):
            try:
                data["summary"] = json.loads(data["summary"])
            except (TypeError, json.JSONDecodeError):
                data["summary"] = None
        data["cancel_requested"] = bool(data["cancel_requested"])
        return data

    # -- artifacts --------------------------------------------------------

    def save_artifact(self, run_id: str, payload: dict[str, Any]) -> int:
        blob = gzip.compress(
            json.dumps(payload, separators=(",", ":"), default=str).encode(), compresslevel=6
        )
        with self._lock, self.connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO artifacts (run_id, payload, bytes, created_at)"
                " VALUES (?, ?, ?, ?)",
                (run_id, blob, len(blob), utcnow()),
            )
        return len(blob)

    def load_artifact(self, run_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT payload FROM artifacts WHERE run_id = ?", (run_id,)
            ).fetchone()
        if row is None:
            return None
        try:
            return json.loads(gzip.decompress(row["payload"]))
        except (OSError, json.JSONDecodeError):
            return None

    # -- settings & audit -------------------------------------------------

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self._lock, self.connect() as conn:
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?)"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    def get_bool(self, key: str, default: bool = False) -> bool:
        raw = self.get_setting(key)
        if raw is None:
            return default
        return raw.strip().lower() in {"1", "true", "yes", "on"}

    def audit(self, action: str, detail: str, *, actor: str = "local") -> None:
        with self._lock, self.connect() as conn:
            conn.execute(
                "INSERT INTO audit (ts, actor, action, detail) VALUES (?, ?, ?, ?)",
                (utcnow(), actor, action, detail),
            )

    def list_audit(self, *, limit: int = 60) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT id, ts, actor, action, detail FROM audit ORDER BY id DESC LIMIT ?",
                (max(1, min(int(limit), 500)),),
            ).fetchall()
        return [dict(row) for row in rows]
