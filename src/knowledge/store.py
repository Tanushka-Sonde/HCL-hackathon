"""SQLite-backed store for documents, chunks, query events and feedback.

Local demo replacement for the PostgreSQL tables. Query events are stored
as a JSON payload plus a few indexed columns used for dashboard filtering.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    doc_id TEXT NOT NULL,
    title TEXT NOT NULL,
    category TEXT,
    version TEXT,
    status TEXT,
    effective_date TEXT,
    mime_type TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    pages INTEGER,
    chunk_count INTEGER NOT NULL DEFAULT 0,
    content_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chunks (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    page INTEGER,
    section TEXT,
    content TEXT NOT NULL,
    index_text TEXT NOT NULL,
    embedding TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_chunks_document ON chunks(document_id);

CREATE TABLE IF NOT EXISTS query_events (
    query_id TEXT PRIMARY KEY,
    ts TEXT NOT NULL,
    session_id TEXT NOT NULL,
    config_id TEXT NOT NULL,
    outcome TEXT NOT NULL,
    total_ms REAL NOT NULL,
    eval_run_id TEXT,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_events_ts ON query_events(ts);

CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query_id TEXT NOT NULL REFERENCES query_events(query_id),
    helpful INTEGER NOT NULL,
    comment TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_feedback_query ON feedback(query_id);

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('admin', 'user')),
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_active_at TEXT NOT NULL,
    query_count INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_sessions_user ON sessions(user_id);

CREATE TABLE IF NOT EXISTS auth_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT,
    user_id TEXT,
    event TEXT NOT NULL,
    success INTEGER NOT NULL,
    ip TEXT,
    detail TEXT,
    ts TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_auth_events_ts ON auth_events(ts);

CREATE TABLE IF NOT EXISTS assets (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page INTEGER,
    kind TEXT NOT NULL,
    path TEXT NOT NULL,
    width INTEGER,
    height INTEGER
);
CREATE INDEX IF NOT EXISTS ix_assets_document ON assets(document_id);
"""

# Columns added after the first release; created on startup if missing.
_ADDED_COLUMNS: dict[str, dict[str, str]] = {
    "feedback": {"user_id": "TEXT"},
    "query_events": {
        "user_id": "TEXT",
        "username": "TEXT",
        "role": "TEXT",
        "input_tokens": "INTEGER NOT NULL DEFAULT 0",
        "output_tokens": "INTEGER NOT NULL DEFAULT 0",
        "cost_usd": "REAL NOT NULL DEFAULT 0",
    },
    "documents": {
        "uploaded_by": "TEXT",
        "vision_input_tokens": "INTEGER NOT NULL DEFAULT 0",
        "vision_output_tokens": "INTEGER NOT NULL DEFAULT 0",
    },
    "chunks": {
        "content_type": "TEXT NOT NULL DEFAULT 'text'",
        "source_method": "TEXT NOT NULL DEFAULT 'plain'",
        "asset_id": "TEXT",
        "bbox": "TEXT",
    },
}

# Public user fields. password_hash is deliberately absent: no API returns it.
USER_PUBLIC_FIELDS = "id, username, role, is_active, created_at"


class KnowledgeStore:
    """Thread-safe wrapper around a single SQLite connection."""

    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._migrate()
            self._conn.commit()

    def _migrate(self) -> None:
        """Add columns introduced after a database was first created."""
        for table, columns in _ADDED_COLUMNS.items():
            existing = {
                r["name"] for r in self._conn.execute(f"PRAGMA table_info({table})")
            }
            for name, decl in columns.items():
                if name not in existing:
                    self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS ix_events_user ON query_events(user_id)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS ix_events_session ON query_events(session_id)"
        )

    def close(self) -> None:
        self._conn.close()

    # ── Documents & chunks ───────────────────────────────────

    def find_document_by_hash(self, content_hash: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM documents WHERE content_hash = ?", (content_hash,)
            ).fetchone()
        return dict(row) if row else None

    def insert_document(
        self,
        doc: dict[str, Any],
        chunks: list[dict[str, Any]],
        assets: list[dict[str, Any]] | None = None,
    ) -> None:
        """Insert a document, its chunks and its assets atomically."""
        with self._lock:
            try:
                self._conn.execute(
                    """INSERT INTO documents (id, filename, doc_id, title, category,
                       version, status, effective_date, mime_type, size_bytes, pages,
                       chunk_count, content_hash, created_at, uploaded_by,
                       vision_input_tokens, vision_output_tokens)
                       VALUES (:id, :filename, :doc_id, :title, :category, :version,
                       :status, :effective_date, :mime_type, :size_bytes, :pages,
                       :chunk_count, :content_hash, :created_at, :uploaded_by,
                       :vision_input_tokens, :vision_output_tokens)""",
                    {
                        "uploaded_by": None,
                        "vision_input_tokens": 0,
                        "vision_output_tokens": 0,
                        **doc,
                    },
                )
                self._conn.executemany(
                    """INSERT INTO chunks (id, document_id, chunk_index, page, section,
                       content, index_text, embedding, content_type, source_method,
                       asset_id, bbox)
                       VALUES (:id, :document_id, :chunk_index, :page, :section,
                       :content, :index_text, :embedding, :content_type,
                       :source_method, :asset_id, :bbox)""",
                    [
                        {
                            "content_type": "text",
                            "source_method": "plain",
                            "asset_id": None,
                            **c,
                            "embedding": json.dumps(c["embedding"]),
                            "bbox": json.dumps(c["bbox"]) if c.get("bbox") else None,
                        }
                        for c in chunks
                    ],
                )
                self._conn.executemany(
                    """INSERT INTO assets (id, document_id, page, kind, path, width,
                       height) VALUES (:id, :document_id, :page, :kind, :path,
                       :width, :height)""",
                    assets or [],
                )
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    def list_documents(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM documents ORDER BY created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def get_asset(self, asset_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM assets WHERE id = ?", (asset_id,)
            ).fetchone()
        return dict(row) if row else None

    def list_chunks(self, document_id: str) -> list[dict[str, Any]]:
        """A document's chunks in order, without embeddings (for the viewer)."""
        with self._lock:
            rows = self._conn.execute(
                """SELECT id, chunk_index, page, section, content, content_type,
                          source_method, asset_id
                   FROM chunks WHERE document_id = ? ORDER BY chunk_index""",
                (document_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def delete_document(self, document_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM documents WHERE id = ?", (document_id,)
            )
            self._conn.commit()
        return cur.rowcount > 0

    def load_chunks(self) -> list[dict[str, Any]]:
        """All chunks joined with document metadata (for building the index)."""
        with self._lock:
            rows = self._conn.execute(
                """SELECT c.id AS chunk_id, c.document_id, c.chunk_index, c.page,
                          c.section, c.content, c.index_text, c.embedding,
                          c.content_type, c.source_method, c.asset_id, c.bbox,
                          d.filename AS document_filename, d.doc_id, d.title,
                          d.category, d.version, d.status
                   FROM chunks c JOIN documents d ON c.document_id = d.id
                   ORDER BY d.created_at, c.chunk_index"""
            ).fetchall()
        result = []
        for r in rows:
            item = dict(r)
            item["embedding"] = json.loads(item["embedding"])
            item["bbox"] = json.loads(item["bbox"]) if item["bbox"] else None
            result.append(item)
        return result

    # ── Query events ─────────────────────────────────────────

    def insert_event(self, event: dict[str, Any]) -> None:
        identity = event["identity"]
        usage = event.get("usage") or {}
        with self._lock:
            self._conn.execute(
                """INSERT INTO query_events (query_id, ts, session_id, config_id,
                   outcome, total_ms, eval_run_id, payload, user_id, username, role,
                   input_tokens, output_tokens, cost_usd)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    identity["query_id"],
                    identity["timestamp"],
                    identity["session_id"],
                    identity["config_id"],
                    event["outcome"]["status"],
                    event["performance"]["total_ms"],
                    (event.get("eval") or {}).get("run_id"),
                    json.dumps(event, default=str),
                    identity.get("user_id"),
                    identity.get("username"),
                    identity.get("role"),
                    usage.get("input_tokens", 0),
                    usage.get("output_tokens", 0),
                    usage.get("estimated_cost_usd", 0.0),
                ),
            )
            self._conn.commit()

    def count_events(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM query_events").fetchone()[0]

    def update_event_payload(self, query_id: str, event: dict[str, Any]) -> None:
        """Replace an event's payload (used to attach evaluation results)."""
        payload = {k: v for k, v in event.items() if k != "feedback"}
        with self._lock:
            self._conn.execute(
                "UPDATE query_events SET payload = ? WHERE query_id = ?",
                (json.dumps(payload, default=str), query_id),
            )
            self._conn.commit()

    def get_event(self, query_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT payload FROM query_events WHERE query_id = ?", (query_id,)
            ).fetchone()
        if row is None:
            return None
        event = json.loads(row["payload"])
        event["feedback"] = self.feedback_for(query_id)
        return event

    def list_events(
        self,
        *,
        config_id: str | None = None,
        outcome: str | None = None,
        since: str | None = None,
        include_eval: bool = True,
        limit: int | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return event payloads (newest first) matching the filters."""
        clauses: list[str] = []
        params: list[Any] = []
        if user_id:
            clauses.append("user_id = ?")
            params.append(user_id)
        if session_id:
            clauses.append("session_id = ?")
            params.append(session_id)
        if config_id:
            clauses.append("config_id = ?")
            params.append(config_id)
        if outcome:
            clauses.append("outcome = ?")
            params.append(outcome)
        if since:
            clauses.append("ts >= ?")
            params.append(since)
        if not include_eval:
            clauses.append("eval_run_id IS NULL")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"SELECT query_id, payload FROM query_events {where} ORDER BY ts DESC"
        if limit:
            sql += " LIMIT ?"
            params.append(limit)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
            fb_rows = self._conn.execute(
                "SELECT query_id, helpful, comment, created_at FROM feedback "
                "ORDER BY created_at"
            ).fetchall()
        latest_fb: dict[str, dict[str, Any]] = {}
        for fb in fb_rows:
            latest_fb[fb["query_id"]] = {
                "helpful": bool(fb["helpful"]),
                "comment": fb["comment"],
                "created_at": fb["created_at"],
            }
        events = []
        for r in rows:
            event = json.loads(r["payload"])
            event["feedback"] = latest_fb.get(r["query_id"])
            events.append(event)
        return events

    # ── Feedback ─────────────────────────────────────────────

    def add_feedback(
        self,
        query_id: str,
        helpful: bool,
        comment: str | None,
        created_at: str,
        user_id: str | None = None,
    ) -> bool:
        with self._lock:
            exists = self._conn.execute(
                "SELECT 1 FROM query_events WHERE query_id = ?", (query_id,)
            ).fetchone()
            if not exists:
                return False
            self._conn.execute(
                "INSERT INTO feedback (query_id, helpful, comment, created_at, "
                "user_id) VALUES (?, ?, ?, ?, ?)",
                (query_id, int(helpful), comment, created_at, user_id),
            )
            self._conn.commit()
        return True

    def feedback_for(self, query_id: str) -> dict[str, Any] | None:
        """Latest feedback for a query (a reviewer may revise their rating)."""
        with self._lock:
            row = self._conn.execute(
                "SELECT helpful, comment, created_at FROM feedback "
                "WHERE query_id = ? ORDER BY id DESC LIMIT 1",
                (query_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "helpful": bool(row["helpful"]),
            "comment": row["comment"],
            "created_at": row["created_at"],
        }

    # ── Users, sessions, auth events ─────────────────────────

    def create_user(self, user: dict[str, Any]) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO users (id, username, password_hash, role, is_active, "
                "created_at) VALUES (:id, :username, :password_hash, :role, "
                ":is_active, :created_at)",
                user,
            )
            self._conn.commit()

    def get_user_credentials(self, username: str) -> dict[str, Any] | None:
        """Internal: includes password_hash. Never return this from an API."""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM users WHERE username = ?", (username,)
            ).fetchone()
        return dict(row) if row else None

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                f"SELECT {USER_PUBLIC_FIELDS} FROM users WHERE id = ?", (user_id,)
            ).fetchone()
        return _public_user(row)

    def list_users(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                f"SELECT {USER_PUBLIC_FIELDS} FROM users ORDER BY created_at"
            ).fetchall()
        return [u for u in (_public_user(r) for r in rows) if u]

    def count_users(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    def record_auth_event(
        self,
        event: str,
        success: bool,
        ts: str,
        *,
        username: str | None = None,
        user_id: str | None = None,
        ip: str | None = None,
        detail: str | None = None,
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO auth_events (username, user_id, event, success, ip, "
                "detail, ts) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (username, user_id, event, int(success), ip, detail, ts),
            )
            self._conn.commit()

    def list_auth_events(self, since: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM auth_events"
        params: list[Any] = []
        if since:
            sql += " WHERE ts >= ?"
            params.append(since)
        with self._lock:
            rows = self._conn.execute(sql + " ORDER BY ts", params).fetchall()
        return [dict(r) for r in rows]

    def session_owner(self, session_id: str) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT user_id FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
        return row["user_id"] if row else None

    def touch_session(self, session_id: str, user_id: str, ts: str) -> None:
        """Create the session on first use; bump activity and query count."""
        with self._lock:
            self._conn.execute(
                "INSERT INTO sessions (session_id, user_id, created_at, "
                "last_active_at, query_count) VALUES (?, ?, ?, ?, 1) "
                "ON CONFLICT(session_id) DO UPDATE SET last_active_at = "
                "excluded.last_active_at, query_count = query_count + 1",
                (session_id, user_id, ts, ts),
            )
            self._conn.commit()

    def list_sessions(self, user_id: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM sessions"
        params: list[Any] = []
        if user_id:
            sql += " WHERE user_id = ?"
            params.append(user_id)
        with self._lock:
            rows = self._conn.execute(
                sql + " ORDER BY last_active_at DESC", params
            ).fetchall()
        return [dict(r) for r in rows]


def _public_user(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    user = dict(row)
    user["is_active"] = bool(user["is_active"])
    return user
