"""
Trace capture and playbook promotion for the AI PC Agent.

This layer adds ECC-style observability to the supervisor's self-healing loop.
When a worker fails, a trace is captured (audit tail + system state + error).
Repeated failure patterns are promoted into machine-readable playbooks that
the supervisor can consult before taking action.

Runs alongside the existing supervisor.py without modifying it.
"""
import json
import os
import time
from datetime import datetime, timezone
from collections import Counter

TRACE_DIR = os.path.expanduser("~/.local/share/ai-pc-agent/traces")
PLAYBOOK_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "playbooks")
FAILURE_THRESHOLD = 3  # repeats before promoting a playbook

_TRACE_LOCK = False


def _ensure_dirs():
    os.makedirs(TRACE_DIR, exist_ok=True)
    os.makedirs(PLAYBOOK_DIR, exist_ok=True)


_ensure_dirs()


def capture_trace(trace_id: str, worker_id: str, error: str, audit_tail: list = None) -> str:
    """Capture a failure trace to disk.

    Args:
        trace_id: Unique identifier for this failure instance.
        worker_id: Which worker failed.
        error: Error message or exception string.
        audit_tail: Last N entries from the audit log for context.

    Returns:
        Path to the trace file.
    """
    trace = {
        "trace_id": trace_id,
        "worker_id": worker_id,
        "error": error,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "system_state": _capture_system_state(),
        "audit_tail": audit_tail or [],
    }

    path = os.path.join(TRACE_DIR, f"trace_{trace_id}.json")
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(trace, f, indent=2)
    os.replace(tmp, path)
    return path


def _capture_system_state() -> dict:
    """Snapshot current system health for the trace."""
    state = {}
    try:
        import psutil
        state["cpu_percent"] = psutil.cpu_percent(interval=0.5)
        state["memory_percent"] = psutil.virtual_memory().percent
        state["disk_percent"] = psutil.disk_usage("/").percent
        state["boot_time"] = datetime.fromtimestamp(
            psutil.boot_time(), tz=timezone.utc
        ).isoformat()
    except ImportError:
        state["psutil"] = "not available"
    except Exception as e:
        state["error"] = str(e)
    return state


def _classify_failure(error: str) -> str:
    """Classify a failure into a pattern type for playbook grouping.

    Returns a short pattern key like 'timeout', 'import_error', 'tool_denied'.
    """
    err_lower = error.lower()

    if "timeout" in err_lower or "timed out" in err_lower:
        return "timeout"
    if "no module named" in err_lower or "importerror" in err_lower:
        return "import_error"
    if "permission denied" in err_lower or "accessdenied" in err_lower:
        return "permission_denied"
    if "connection" in err_lower and "refused" in err_lower:
        return "connection_refused"
    if "disk" in err_lower and "space" in err_lower:
        return "disk_full"
    if "rate limit" in err_lower or "429" in err_lower:
        return "rate_limit"
    if "not found" in err_lower or "filenotfound" in err_lower:
        return "file_not_found"
    if "denied" in err_lower or "[denied]" in err_lower:
        return "action_denied"

    return "generic_error"


def check_for_playbook_promotion(pattern: str) -> str | None:
    """Check if a failure pattern has enough traces to promote to a playbook.

    If so, generate the playbook file and return its path.
    """
    if not os.path.isdir(TRACE_DIR):
        return None

    pattern_traces = []
    for fname in os.listdir(TRACE_DIR):
        if not fname.startswith("trace_") or not fname.endswith(".json"):
            continue
        try:
            with open(os.path.join(TRACE_DIR, fname), "r") as f:
                trace = json.load(f)
            if _classify_failure(trace.get("error", "")) == pattern:
                pattern_traces.append(trace)
        except (json.JSONDecodeError, OSError):
            continue

    if len(pattern_traces) < FAILURE_THRESHOLD:
        return None

    # Check if playbook already exists
    playbook_path = os.path.join(PLAYBOOK_DIR, f"{pattern}.md")
    if os.path.exists(playbook_path):
        # Update existing playbook with new traces
        _update_playbook(playbook_path, pattern, pattern_traces)
        return playbook_path

    # Create new playbook
    return _create_playbook(pattern, pattern_traces)


def _create_playbook(pattern: str, traces: list[dict]) -> str:
    """Generate a playbook Markdown file from failure traces."""
    errors = [t["error"] for t in traces]
    error_counter = Counter(errors)
    common_error = error_counter.most_common(1)[0][0]

    system_states = [t.get("system_state", {}) for t in traces]

    lines = [
        f"---",
        f"name: auto_fix_{pattern}",
        f"description: Auto-repair playbook for '{pattern}' failures",
        f"risk: medium",
        f"trigger_pattern: {pattern}",
        f"failure_count: {len(traces)}",
        f"---",
        f"",
        f"# Playbook: {pattern}",
        f"",
        f"## Trigger",
        f"Activated when a worker fails with a '{pattern}' classification.",
        f"",
        f"## Observed Error",
        f"Most common error: `{common_error}`",
        f"",
        f"## System State at Failure",
    ]

    if system_states:
        sample = system_states[0]
        for k, v in sample.items():
            lines.append(f"- {k}: {v}")

    lines.extend([
        "",
        "## Repair Steps",
        "1. Log the failure trace for manual review.",
        "2. Restart the affected worker via the supervisor.",
        "3. Capture a fresh trace after restart.",
        f"4. If the failure recurs ({FAILURE_THRESHOLD} times), escalate to human review.",
        "",
        "## Rollback",
        "If restart does not resolve the issue within 2 cycles:",
        "- Revert to the last known-good worker snapshot",
        "- Notify the user of repeated failures",
        "",
        "## Prevention",
        "- Monitor system resources during this operation type",
        "- Consider adding a pre-check before the triggering action",
        "",
        "## Related Failures",
        f"Total occurrences tracked: {len(traces)}",
        "",
    ])

    playbook_path = os.path.join(PLAYBOOK_DIR, f"{pattern}.md")
    with open(playbook_path, "w") as f:
        f.write("\n".join(lines))

    return playbook_path


def _update_playbook(path: str, pattern: str, traces: list[dict]):
    """Update an existing playbook with new trace data (append occurrence count)."""
    try:
        with open(path, "r") as f:
            content = f.read()
        # Update failure_count in frontmatter
        import re
        content = re.sub(
            r"failure_count: \d+",
            f"failure_count: {len(traces)}",
            content,
        )
        with open(path, "w") as f:
            f.write(content)
    except Exception:
        pass


def load_playbooks() -> list[dict]:
    """Load all playbook files for supervisor consultation."""
    playbooks = []
    if not os.path.isdir(PLAYBOOK_DIR):
        return playbooks

    for fname in sorted(os.listdir(PLAYBOOK_DIR)):
        if not fname.endswith(".md"):
            continue
        try:
            with open(os.path.join(PLAYBOOK_DIR, fname), "r") as f:
                content = f.read()
            playbooks.append({
                "name": fname.replace(".md", ""),
                "path": os.path.join(PLAYBOOK_DIR, fname),
                "content": content,
            })
        except OSError:
            continue

    return playbooks


def get_relevant_playbook(error: str) -> str | None:
    """Given an error, return the name of a matching playbook if one exists."""
    pattern = _classify_failure(error)
    path = os.path.join(PLAYBOOK_DIR, f"{pattern}.md")
    if os.path.exists(path):
        return pattern
    return None


# Integration point for the supervisor
def record_worker_failure(worker_id: str, error: str, audit_tail: list = None) -> dict:
    """Called by the supervisor when a worker fails.

    Captures a trace, checks for playbook promotion, and returns
    recommended next action.
    """
    from status import set_error

    trace_id = f"{worker_id}_{int(time.time())}"
    pattern = _classify_failure(error)

    set_error(f"{worker_id}: {error}")

    # Capture trace
    trace_path = capture_trace(trace_id, worker_id, error, audit_tail)

    # Check for playbook promotion
    playbook = check_for_playbook_promotion(pattern)

    # Check if an existing playbook covers this
    existing = get_relevant_playbook(error)

    recommendation = {
        "trace_id": trace_id,
        "trace_path": trace_path,
        "pattern": pattern,
        "playbook_promoted": playbook is not None,
        "playbook_path": playbook,
        "existing_playbook": existing,
        "recommended_action": _recommend_action(pattern, existing is not None),
    }

    return recommendation


def _recommend_action(pattern: str, has_playbook: bool) -> str:
    """Return a recommended repair action based on failure pattern."""
    if pattern == "timeout":
        return "restart_worker" if not has_playbook else "consult_playbook"
    if pattern == "import_error":
        return "reinstall_dependency"
    if pattern == "rate_limit":
        return "switch_backend"
    if pattern == "permission_denied":
        return "request_user_consent"
    if pattern == "disk_full":
        return "cleanup_temp_files"
    if pattern == "connection_refused" or pattern == "file_not_found":
        return "retry_with_backoff"

    return "restart_worker"


if __name__ == "__main__":
    # Self-test
    test_errors = [
        "Connection to server timed out after 30s",
        "No module named 'requests'",
        "Permission denied: '/etc/shadow'",
        "HTTP 429: quota exceeded",
        "FileNotFoundError: '/tmp/foo'",
    ]
    print("=== Trace classification test ===")
    for e in test_errors:
        print(f"  '{e}' → pattern: {_classify_failure(e)}")

    print(f"\nPlaybooks available: {len(load_playbooks())}")
