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
"""


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
            self._conn.commit()

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
        self, doc: dict[str, Any], chunks: list[dict[str, Any]]
    ) -> None:
        """Insert a document and its chunks atomically."""
        with self._lock:
            try:
                self._conn.execute(
                    """INSERT INTO documents (id, filename, doc_id, title, category,
                       version, status, effective_date, mime_type, size_bytes, pages,
                       chunk_count, content_hash, created_at)
                       VALUES (:id, :filename, :doc_id, :title, :category, :version,
                       :status, :effective_date, :mime_type, :size_bytes, :pages,
                       :chunk_count, :content_hash, :created_at)""",
                    doc,
                )
                self._conn.executemany(
                    """INSERT INTO chunks (id, document_id, chunk_index, page, section,
                       content, index_text, embedding)
                       VALUES (:id, :document_id, :chunk_index, :page, :section,
                       :content, :index_text, :embedding)""",
                    [{**c, "embedding": json.dumps(c["embedding"])} for c in chunks],
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
                          d.filename AS document_filename, d.doc_id, d.title,
                          d.category, d.version, d.status
                   FROM chunks c JOIN documents d ON c.document_id = d.id
                   ORDER BY d.created_at, c.chunk_index"""
            ).fetchall()
        result = []
        for r in rows:
            item = dict(r)
            item["embedding"] = json.loads(item["embedding"])
            result.append(item)
        return result

    # ── Query events ─────────────────────────────────────────

    def insert_event(self, event: dict[str, Any]) -> None:
        identity = event["identity"]
        with self._lock:
            self._conn.execute(
                """INSERT INTO query_events (query_id, ts, session_id, config_id,
                   outcome, total_ms, eval_run_id, payload)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    identity["query_id"],
                    identity["timestamp"],
                    identity["session_id"],
                    identity["config_id"],
                    event["outcome"]["status"],
                    event["performance"]["total_ms"],
                    (event.get("eval") or {}).get("run_id"),
                    json.dumps(event, default=str),
                ),
            )
            self._conn.commit()

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
    ) -> list[dict[str, Any]]:
        """Return event payloads (newest first) matching the filters."""
        clauses: list[str] = []
        params: list[Any] = []
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
        self, query_id: str, helpful: bool, comment: str | None, created_at: str
    ) -> bool:
        with self._lock:
            exists = self._conn.execute(
                "SELECT 1 FROM query_events WHERE query_id = ?", (query_id,)
            ).fetchone()
            if not exists:
                return False
            self._conn.execute(
                "INSERT INTO feedback (query_id, helpful, comment, created_at) "
                "VALUES (?, ?, ?, ?)",
                (query_id, int(helpful), comment, created_at),
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
