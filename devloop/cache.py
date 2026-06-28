"""SQLite cache for repo skeletons and tool call results.

Key design:
- All cache keys are derived from git commit hash + content hash → safe to
  read from disk concurrently; only one writer at a time per row.
- TTL eviction is a soft mechanism — entries older than ttl_days are skipped
  but not actively deleted (cheap and good-enough).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS repo_skeleton (
    commit_hash TEXT PRIMARY KEY,
    repo_path TEXT NOT NULL,
    content_json TEXT NOT NULL,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS tool_call_cache (
    cache_key TEXT PRIMARY KEY,
    commit_hash TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    args_json TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS explorer_perspective_cache (
    cache_key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tool_commit ON tool_call_cache(commit_hash);
CREATE INDEX IF NOT EXISTS idx_tool_created ON tool_call_cache(created_at);
CREATE INDEX IF NOT EXISTS idx_explorer_created ON explorer_perspective_cache(created_at);
"""


def hash_args(name: str, args: dict[str, Any]) -> str:
    raw = json.dumps({"name": name, "args": args}, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


class CacheBackend:
    """SQLite-backed cache. Thread-safe via per-thread connections.

    Use as a context manager to guarantee cleanup:

        with CacheBackend(path) as cache:
            ...

    or call ``close()`` explicitly.
    """

    def __init__(self, db_path: Path, ttl_days: int = 7):
        self.db_path = db_path
        self.ttl_seconds = ttl_days * 24 * 3600
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._all_conns: list[sqlite3.Connection] = []
        self._all_conns_lock = threading.Lock()
        self._init_schema()

    def __enter__(self) -> CacheBackend:
        return self

    def __exit__(self, *args) -> None:
        self.close()

    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn"):
            conn = sqlite3.connect(
                self.db_path,
                check_same_thread=False,
                isolation_level=None,
            )
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            self._local.conn = conn
            with self._all_conns_lock:
                self._all_conns.append(conn)
        return self._local.conn

    def _init_schema(self) -> None:
        conn = self._conn()
        for stmt in SCHEMA_SQL.strip().split(";"):
            s = stmt.strip()
            if s:
                conn.execute(s)

    # ---- Repo skeleton ----

    def get_skeleton(self, commit_hash: str) -> dict[str, Any] | None:
        row = self._conn().execute(
            "SELECT content_json, created_at FROM repo_skeleton WHERE commit_hash = ?",
            (commit_hash,),
        ).fetchone()
        if not row:
            return None
        content_json, created_at = row
        if (time.time() - created_at) > self.ttl_seconds:
            return None
        return json.loads(content_json)

    def set_skeleton(
        self, commit_hash: str, repo_path: str, content: dict[str, Any]
    ) -> None:
        self._conn().execute(
            "INSERT OR REPLACE INTO repo_skeleton (commit_hash, repo_path, content_json, created_at) VALUES (?,?,?,?)",
            (commit_hash, repo_path, json.dumps(content, ensure_ascii=False), time.time()),
        )

    # ---- Tool call cache ----

    def get_tool(
        self,
        commit_hash: str,
        tool_name: str,
        args: dict[str, Any],
    ) -> Any | None:
        key = self._tool_key(commit_hash, tool_name, args)
        row = self._conn().execute(
            "SELECT result_json, created_at FROM tool_call_cache WHERE cache_key = ?",
            (key,),
        ).fetchone()
        if not row:
            return None
        result_json, created_at = row
        if (time.time() - created_at) > self.ttl_seconds:
            return None
        return json.loads(result_json)

    def set_tool(
        self,
        commit_hash: str,
        tool_name: str,
        args: dict[str, Any],
        result: Any,
    ) -> None:
        key = self._tool_key(commit_hash, tool_name, args)
        self._conn().execute(
            "INSERT OR REPLACE INTO tool_call_cache "
            "(cache_key, commit_hash, tool_name, args_json, result_json, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (
                key,
                commit_hash,
                tool_name,
                json.dumps(args, ensure_ascii=False, sort_keys=True),
                json.dumps(result, ensure_ascii=False, default=str),
                time.time(),
            ),
        )

    def _tool_key(
        self, commit_hash: str, tool_name: str, args: dict[str, Any]
    ) -> str:
        return f"{commit_hash[:12]}:{tool_name}:{hash_args(tool_name, args)}"

    def invalidate_commit(self, commit_hash: str) -> int:
        c1 = self._conn().execute(
            "DELETE FROM repo_skeleton WHERE commit_hash = ?", (commit_hash,)
        ).rowcount
        c2 = self._conn().execute(
            "DELETE FROM tool_call_cache WHERE commit_hash = ?", (commit_hash,)
        ).rowcount
        return c1 + c2

    # ---- Explorer perspective cache (DevLoop Sprint D — todo D2) ----

    def get_perspective(self, cache_key: str) -> str | None:
        """Return the raw JSON-encoded Perspective for ``cache_key`` or ``None``.

        Returns ``None`` if the entry is missing or older than ``ttl_seconds``.
        """
        row = self._conn().execute(
            "SELECT value_json, created_at FROM explorer_perspective_cache WHERE cache_key = ?",
            (cache_key,),
        ).fetchone()
        if not row:
            return None
        value_json, created_at = row
        if (time.time() - created_at) > self.ttl_seconds:
            return None
        return value_json

    def set_perspective(self, cache_key: str, value_json: str) -> None:
        """Store ``value_json`` (an already-serialized Perspective) under ``cache_key``."""
        self._conn().execute(
            "INSERT OR REPLACE INTO explorer_perspective_cache "
            "(cache_key, value_json, created_at) VALUES (?,?,?)",
            (cache_key, value_json, time.time()),
        )

    def clear_perspectives(self) -> int:
        """Delete every cached explorer Perspective. Returns the row count removed."""
        return self._conn().execute("DELETE FROM explorer_perspective_cache").rowcount

    def clear_all(self) -> int:
        """Delete every cached entry (skeletons, tool calls, explorer perspectives).

        Used by ``devloop cache clear``. Returns the total number of rows removed.
        """
        conn = self._conn()
        n = 0
        for table in ("repo_skeleton", "tool_call_cache", "explorer_perspective_cache"):
            n += conn.execute(f"DELETE FROM {table}").rowcount
        return n

    def close(self) -> None:
        """Close all connections opened from any thread."""
        with self._all_conns_lock:
            for c in self._all_conns:
                try:
                    c.close()
                except Exception:
                    pass
            self._all_conns.clear()
        # Reset thread-local for the current thread
        if hasattr(self._local, "conn"):
            try:
                delattr(self._local, "conn")
            except AttributeError:
                pass


class NullCache(CacheBackend):
    """No-op cache for tests."""

    def __init__(self) -> None:
        pass

    def get_skeleton(self, commit_hash: str):  # type: ignore[override]
        return None

    def set_skeleton(self, *a, **kw):  # type: ignore[override]
        pass

    def get_tool(self, *a, **kw):  # type: ignore[override]
        return None

    def set_tool(self, *a, **kw):  # type: ignore[override]
        pass

    def invalidate_commit(self, *a, **kw):  # type: ignore[override]
        return 0

    def get_perspective(self, *a, **kw):  # type: ignore[override]
        return None

    def set_perspective(self, *a, **kw):  # type: ignore[override]
        pass

    def clear_perspectives(self, *a, **kw):  # type: ignore[override]
        return 0

    def clear_all(self, *a, **kw):  # type: ignore[override]
        return 0

    def close(self) -> None:  # type: ignore[override]
        pass
