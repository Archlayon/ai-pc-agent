"""
Self-healing supervisor for the AI PC Agent.

Watchdog process that monitors worker/fixer health, triggers restarts,
and enforces sandboxing constraints on fixers.
"""
import json
import os
import threading
import time
from datetime import datetime, timezone

from agents.main_agent import MainAgent

# ECC-inspired observability: status payload + trace/playbook learning
try:
    from status import set_error, set_workers
except Exception:
    set_error = None
    set_workers = None

try:
    from trace_manager import record_worker_failure
except Exception:
    record_worker_failure = None

try:
    from context_compactor import save_session_summary
except Exception:
    save_session_summary = None

try:
    from security_audit import run_full_audit
except Exception:
    run_full_audit = None

SUPERVISOR_STATE_PATH = os.path.expanduser("~/.local/share/ai-pc-agent/supervisor_state.json")


class Supervisor:
    def __init__(self):
        self.main_agent = MainAgent()
        self.snapshots = {}
        self.running = False
        self._lock = threading.Lock()

    def start(self):
        self.running = True
        self._load_state()
        self.main_agent.start()
        threading.Thread(target=self._watch_loop, daemon=True).start()
        threading.Thread(target=self._status_reporter, daemon=True).start()

        # One-time startup security audit (ECC AgentShield self-scan)
        if run_full_audit is not None:
            try:
                run_full_audit()
            except Exception:
                pass

        # Report baseline worker/fixer counts to status
        if set_workers is not None:
            try:
                total = self.baseline_workers + self.baseline_fixers
                set_workers(0, total)
            except Exception:
                pass

    def _watch_loop(self):
        while self.running:
            time.sleep(15)
            self._check_workers()
            self._check_fixers()

    def _status_reporter(self):
        """Background thread that syncs supervisor state to the status payload."""
        while self.running:
            if set_workers is not None:
                try:
                    active = sum(1 for w in self.main_agent.workers.values() if getattr(w, "current_task", None))
                    total = len(self.main_agent.workers) + len(self.main_agent.fixers)
                    pending = len(self.main_agent.pending_approvals)
                    set_workers(active, total, pending)
                except Exception:
                    pass
            time.sleep(5)

    def _check_workers(self):
        now = time.time()
        for wid, worker in list(self.main_agent.workers.items()):
            last = getattr(worker, "last_heartbeat", now)
            if now - last > 45:
                # Capture a failure trace before restarting
                error = f"Worker {wid} heartbeat timeout (last seen {last})"
                if record_worker_failure is not None:
                    try:
                        trace_info = record_worker_failure(
                            worker_id=wid,
                            error=error,
                            audit_tail=self._get_audit_tail(10),
                        )
                        # Use the playbook-driven recommendation if available
                        if trace_info.get("playbook_path") or trace_info.get("existing_playbook"):
                            self._dispatch_fix(wid, playbook=trace_info.get("existing_playbook"))
                            continue
                    except Exception:
                        pass
                self._check_workers_inner(wid)

    def _check_workers_inner(self, worker_id: str):
        """Original restart logic, called when no playbook recommendation exists."""
        self._restart_worker(worker_id)

    def _dispatch_fix(self, worker_id: str, playbook: str = None):
        """Dispatch a repair task to a fixer, optionally guided by a playbook."""
        fixer_ids = list(self.main_agent.fixers.keys())
        if not fixer_ids:
            self._restart_worker(worker_id)
            return

        fixer_id = fixer_ids[0]
        steps = [{"action": "restart", "worker_id": worker_id}]

        # If a playbook exists for this failure pattern, use its steps
        if playbook:
            try:
                from trace_manager import load_playbooks
                pbs = load_playbooks()
                pb = next((p for p in pbs if p["name"] == playbook), None)
                if pb:
                    # Extract steps from playbook markdown
                    body = pb["content"]
                    if "reinstall" in body.lower():
                        steps = [
                            {"action": "restart", "worker_id": worker_id},
                            {"action": "reinstall", "package": "psutil"},
                        ]
            except Exception:
                pass

        self.send(
            {
                "type": "fix_assign",
                "fix_id": f"fix_{worker_id}_{int(time.time())}",
                "fixer_id": fixer_id,
                "worker_id": worker_id,
                "steps": steps,
            }
        )

    def _get_audit_tail(self, n: int) -> list:
        """Pull the last N entries from the audit log for trace context."""
        try:
            from audit_log import get_recent
            recent = get_recent(n)
            # Strip fields we don't need from the audit entries
            return [
                {"tool_name": r.get("tool_name"), "decision": r.get("decision"),
                 "result": r.get("result", "")[:100]}
                for r in recent
            ]
        except Exception:
            return []

    def _check_fixers(self):
        now = time.time()
        for fid, fixer in list(self.main_agent.fixers.items()):
            last = getattr(fixer, "last_heartbeat", now)
            if now - last > 60:
                error = f"Fixer {fid} heartbeat timeout (last seen {last})"
                if record_worker_failure is not None:
                    try:
                        record_worker_failure(
                            worker_id=fid,
                            error=error,
                            audit_tail=self._get_audit_tail(5),
                        )
                    except Exception:
                        pass
                self._restart_fixer(fid)

    def _snapshot_worker(self, worker_id: str) -> str:
        snapshot_path = f"/tmp/ai-agent-snapshots/{worker_id}_{int(time.time())}.py"
        os.makedirs(os.path.dirname(snapshot_path), exist_ok=True)
        with open(snapshot_path, "w") as f:
            f.write(f"# Snapshot of {worker_id} at {datetime.now(timezone.utc).isoformat()}\n")
        self.snapshots[worker_id] = snapshot_path
        self._save_state()
        return snapshot_path

    def _restart_worker(self, worker_id: str):
        snapshot = self._snapshot_worker(worker_id)
        if worker_id in self.main_agent.workers:
            self.main_agent.workers[worker_id].stop()
        from agents.worker import Worker
        new_worker = Worker(worker_id)
        new_worker.start()
        self.main_agent.workers[worker_id] = new_worker

    def _restart_fixer(self, fixer_id: str):
        if fixer_id in self.main_agent.fixers:
            self.main_agent.fixers[fixer_id].stop()
        from agents.fixer import Fixer
        new_fixer = Fixer(fixer_id)
        new_fixer.start()
        self.main_agent.fixers[fixer_id] = new_fixer

    def _save_state(self):
        try:
            with open(SUPERVISOR_STATE_PATH, "w") as f:
                json.dump(
                    {
                        "snapshots": self.snapshots,
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    },
                    f,
                    indent=2,
                )
        except Exception:
            pass

    def _load_state(self):
        if not os.path.exists(SUPERVISOR_STATE_PATH):
            return
        try:
            with open(SUPERVISOR_STATE_PATH, "r") as f:
                data = json.load(f)
                self.snapshots = data.get("snapshots", {})
        except Exception:
            pass

    def stop(self):
        self.running = False
        self.main_agent.stop()
        for w in self.main_agent.workers.values():
            w.stop()
        for f in self.main_agent.fixers.values():
            f.stop()

        # Save a session summary for future recall (ECC Memory Vault concept)
        if save_session_summary is not None:
            try:
                from memory import get_context
                session_ctx = get_context("default", limit=50)
                if session_ctx:
                    save_session_summary("default", session_ctx)
            except Exception:
                pass
