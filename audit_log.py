"""
Audit log for the AI PC Agent.

Records every action attempt, approved or declined, to a local SQLite database.
"""
import json
import os
import sqlite3
from datetime import datetime, timezone

DB_PATH = os.path.expanduser("~/.local/share/ai-pc-agent/audit.db")


def _ensure_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            tool_name TEXT NOT NULL,
            args TEXT NOT NULL,
            decision TEXT NOT NULL,
            result TEXT,
            user_input TEXT
        )
        """
    )
    conn.commit()
    return conn


def log_action(tool_name: str, args: dict, decision: str, result: str = "", user_input: str = ""):
    conn = _ensure_db()
    conn.execute(
        "INSERT INTO actions (timestamp, tool_name, args, decision, result, user_input) VALUES (?, ?, ?, ?, ?, ?)",
        (
            datetime.now(timezone.utc).isoformat(),
            tool_name,
            json.dumps(args),
            decision,
            result,
            user_input,
        ),
    )
    conn.commit()
    conn.close()


def get_recent(limit: int = 50):
    conn = _ensure_db()
    rows = conn.execute(
        "SELECT id, timestamp, tool_name, args, decision, result FROM actions ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [
        {
            "id": r[0],
            "timestamp": r[1],
            "tool_name": r[2],
            "args": json.loads(r[3]),
            "decision": r[4],
            "result": r[5],
        }
        for r in rows
    ]
