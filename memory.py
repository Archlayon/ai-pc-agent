"""
Conversation memory for the AI PC Agent.

Persists across restarts, kept compact (SQLite — queryable, prunable).
"""
import json
import os
import sqlite3
from datetime import datetime, timezone

DB_PATH = os.path.expanduser("~/.local/share/ai-pc-agent/memory.db")
MAX_CONTEXT_MESSAGES = 20


def _ensure_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            timestamp TEXT NOT NULL
        )
        """
    )
    conn.commit()
    return conn


def append_message(session_id: str, role: str, content: str):
    conn = _ensure_db()
    conn.execute(
        "INSERT INTO messages (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
        (session_id, role, content, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()


def get_context(session_id: str, limit: int = MAX_CONTEXT_MESSAGES):
    conn = _ensure_db()
    rows = conn.execute(
        "SELECT role, content FROM messages WHERE session_id = ? ORDER BY id DESC LIMIT ?",
        (session_id, limit),
    ).fetchall()
    conn.close()
    return [{"role": r[0], "content": r[1]} for r in reversed(rows)]


def prune_old(session_id: str, keep: int = MAX_CONTEXT_MESSAGES):
    conn = _ensure_db()
    conn.execute(
        """
        DELETE FROM messages
        WHERE session_id = ? AND id NOT IN (
            SELECT id FROM messages WHERE session_id = ? ORDER BY id DESC LIMIT ?
        )
        """,
        (session_id, session_id, keep),
    )
    conn.commit()
    conn.close()
