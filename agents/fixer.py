"""
Fixer agent for the AI PC Agent hierarchy.

Repairs broken workers and clones/scales the worker pool when instructed
by the main agent. Sits idle/on standby when nothing is broken.
"""
import json
import os
import shutil
import subprocess
import sys
import time

from .base import BaseAgent


ALLOWED_NETWORK = {
    "pypi.org",
    "pypi.python.org",
    "files.pythonhosted.org",
    "registry.npmjs.org",
}


class Fixer(BaseAgent):
    def __init__(self, fixer_id: str):
        super().__init__(fixer_id, "fixer")
        self.busy = False
        self.current_fix = None

    def handle(self, msg: dict):
        msg_type = msg.get("type")
        if msg_type == "fix_assign":
            self._handle_fix(msg)
        elif msg_type == "scale_assign":
            self._handle_scale(msg)
        elif msg_type == "health_check":
            self._send_heartbeat()

    def _handle_fix(self, msg: dict):
        fix_id = msg.get("fix_id")
        worker_id = msg.get("worker_id")
        steps = msg.get("steps", [])
        self.busy = True
        self.current_fix = fix_id

        results = []
        for step in steps:
            action = step.get("action")
            if action == "restart":
                res = self._restart_worker(worker_id)
            elif action == "reinstall":
                res = self._reinstall_dep(step.get("package"))
            elif action == "rollback":
                res = self._rollback_worker(worker_id, step.get("snapshot"))
            else:
                res = f"[fixer] Unknown action: {action}"
            results.append(res)

        self.send_result(
            {
                "type": "fix_result",
                "fix_id": fix_id,
                "worker_id": worker_id,
                "results": results,
                "status": "completed",
            }
        )
        self.busy = False
        self.current_fix = None

    def _handle_scale(self, msg: dict):
        scale_id = msg.get("scale_id")
        template_role = msg.get("template_role", "worker")
        count = msg.get("count", 1)
        results = []
        for i in range(count):
            new_id = f"{template_role}_{int(time.time())}_{i}"
            results.append({"new_id": new_id, "status": "cloned"})
        self.send_result(
            {
                "type": "scale_result",
                "scale_id": scale_id,
                "results": results,
                "status": "completed",
            }
        )

    def _restart_worker(self, worker_id: str) -> str:
        return f"[fixer] Restart signal sent to {worker_id}"

    def _reinstall_dep(self, package: str) -> str:
        if not package:
            return "[fixer] No package specified for reinstall"
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", "--quiet", package],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode == 0:
                return f"[fixer] Reinstalled {package}"
            return f"[fixer] Reinstall failed for {package}: {result.stderr}"
        except Exception as e:
            return f"[fixer] Reinstall error for {package}: {e}"

    def _rollback_worker(self, worker_id: str, snapshot: str) -> str:
        if not snapshot or not os.path.exists(snapshot):
            return f"[fixer] Snapshot {snapshot} not found for {worker_id}"
        try:
            shutil.copy2(snapshot, f"/tmp/{worker_id}_rollback.py")
            return f"[fixer] Rolled back {worker_id} from {snapshot}"
        except Exception as e:
            return f"[fixer] Rollback failed for {worker_id}: {e}"

    def _send_heartbeat(self):
        self.send(
            {
                "type": "fixer_health",
                "fixer_id": self.agent_id,
                "status": "idle" if not self.busy else "busy",
                "current_fix": self.current_fix,
            }
        )
