"""
Observability status payload for the AI PC Agent.

Exports a machine-readable JSON file describing the agent's current state.
This runs as a side-channel (outside the LLM context) so the tray icon,
logs, and debugging tools can inspect the agent without querying the ZMQ bus.

Mirrors the ECC reference architecture's HUD/status contract:
context pressure, tool activity, agent state, queue state, cost/risk.
"""
import json
import os
import threading
import time
from datetime import datetime, timezone

STATUS_PATH = os.path.expanduser("~/.local/share/ai-pc-agent/status.json")
STATUS_INTERVAL = 5  # seconds between status refreshes

_status_lock = threading.Lock()
_status = {
    "context_messages": 0,
    "context_limit": 20,
    "compaction_risk": "unknown",
    "active_workers": 0,
    "idle_workers": 0,
    "pending_tasks": 0,
    "last_error": None,
    "last_error_ts": None,
    "session_id": "default",
    "cost_estimate_usd": 0.0,
    "autonomy_mode": False,
    "updated_at": None,
}


def _ensure_dir():
    os.makedirs(os.path.dirname(STATUS_PATH), exist_ok=True)


def update(**kwargs):
    """Update one or more status fields and flush to disk immediately."""
    with _status_lock:
        _status.update(kwargs)
        _status["updated_at"] = datetime.now(timezone.utc).isoformat()
        data = dict(_status)
    _ensure_dir()
    # Atomic write: write temp then rename
    tmp = STATUS_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, STATUS_PATH)
    return data


def set_context(messages: int, limit: int = 20):
    """Report current conversation context pressure."""
    usage = messages / max(limit, 1)
    if usage > 0.85:
        risk = "high"
    elif usage > 0.6:
        risk = "medium"
    else:
        risk = "low"
    update(context_messages=messages, context_limit=limit, compaction_risk=risk)


def set_workers(active: int, total: int, pending_tasks: int = 0):
    update(
        active_workers=active,
        idle_workers=max(total - active, 0),
        pending_tasks=pending_tasks,
    )


def set_error(error_msg: str):
    update(
        last_error=error_msg,
        last_error_ts=datetime.now(timezone.utc).isoformat(),
    )


def set_autonomy(enabled: bool):
    update(autonomy_mode=enabled)


def add_cost(amount_usd: float):
    with _status_lock:
        _status["cost_estimate_usd"] += amount_usd


def get_status() -> dict:
    """Read the current in-memory status snapshot."""
    with _status_lock:
        return dict(_status)


def load_status() -> dict:
    """Load status from disk (e.g., by an external monitor process)."""
    try:
        with open(STATUS_PATH, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def start_watcher(stop_event=None):
    """Background thread that periodically refreshes the status file.

    Call this from the tray/supervisor to keep status.json fresh
    without blocking the main loop.
    """
    while stop_event is None or not stop_event.is_set():
        _ensure_dir()
        with _status_lock:
            _status["updated_at"] = datetime.now(timezone.utc).isoformat()
            data = dict(_status)
        tmp = STATUS_PATH + ".tmp"
        try:
            with open(tmp, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp, STATUS_PATH)
        except Exception:
            pass
        time.sleep(STATUS_INTERVAL)


# CLI entry point for inspecting status
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="AI PC Agent status reporter")
    parser.add_argument("--watch", action="store_true", help="Continuously refresh status.json")
    parser.add_argument("--print", action="store_true", help="Print current status to stdout")
    args = parser.parse_args()

    if args.print:
        print(json.dumps(load_status(), indent=2))
    elif args.watch:
        stop = threading.Event()
        try:
            start_watcher(stop)
        except KeyboardInterrupt:
            stop.set()
    else:
        print(json.dumps(load_status(), indent=2))
