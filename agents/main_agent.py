"""
Main agent for the AI PC Agent hierarchy.

Central decision-maker and coordinator. Receives reports from every worker
and fixer via ZMQ result bus, dispatches triage work, verifies fixes,
decides on user approval, and makes final calls before anything reaches the user.
"""
import json
import os
import subprocess
import sys
import threading
import time

from llm_client import ask_agent, _generate_with_timeout
from settings import get_settings

from .base import BaseAgent
from .worker import Worker
from .fixer import Fixer
from .research_worker import ResearchWorker


class MainAgent(BaseAgent):
    def __init__(self):
        super().__init__("main_agent", "main")
        self.workers = {}
        self.research_workers = {}
        self.fixers = {}
        self.task_results = {}
        self.fix_results = {}
        self.scale_results = {}
        self.pending_approvals = []
        self.baseline_workers = 3
        self.baseline_research_workers = 1
        self.baseline_fixers = 2
        self.idle_grace = 3600
        self._lock = threading.Lock()
        self._round_robin = 0

    def start(self):
        self._spawn_baseline()
        super().start()
        threading.Thread(target=self._result_loop, daemon=True).start()
        threading.Thread(target=self._input_loop, daemon=True).start()
        threading.Thread(target=self._health_loop, daemon=True).start()
        threading.Thread(target=self._scale_down_loop, daemon=True).start()

    def _spawn_baseline(self):
        settings = get_settings()
        self.baseline_workers = settings.get("max_workers", 3)
        self.baseline_research_workers = settings.get("max_research_workers", 1)
        self.baseline_fixers = settings.get("max_fixers", 2)
        self.idle_grace = settings.get("idle_grace_seconds", 3600)

        for i in range(self.baseline_fixers):
            fixer = Fixer(f"fixer_{i}")
            fixer.start()
            self.fixers[fixer.agent_id] = fixer

        for i in range(self.baseline_workers):
            worker = Worker(f"worker_{i}")
            worker.start()
            self.workers[worker.agent_id] = worker

        for i in range(self.baseline_research_workers):
            rworker = ResearchWorker(f"research_worker_{i}")
            rworker.start()
            self.research_workers[rworker.agent_id] = rworker

    def handle(self, msg: dict):
        msg_type = msg.get("type")
        if msg_type == "user_request":
            self._handle_user_request(msg)
        elif msg_type == "worker_health":
            self._handle_worker_health(msg)
        elif msg_type == "fixer_health":
            self._handle_fixer_health(msg)

    def _result_loop(self):
        while self.running:
            msg = self.bus.recv_result(timeout_ms=500)
            if msg is None:
                continue
            self._handle_result(msg)

    def _input_loop(self):
        while self.running:
            msg = self.bus.recv_input(timeout_ms=500)
            if msg is None:
                continue
            self._handle_input(msg)

    def _handle_input(self, msg: dict):
        msg_type = msg.get("type")
        if msg_type == "user_request":
            self._handle_user_request(msg)
        elif msg_type == "widget_command":
            self._handle_widget_command(msg)

    def _handle_widget_command(self, msg: dict):
        command = msg.get("command")
        request_id = msg.get("request_id", "widget")
        if command == "resize":
            self.publish_response({"type": "widget_resize", "request_id": request_id})
        elif command == "toggle_listen":
            self.publish_response({"type": "widget_toggle_listen", "request_id": request_id, "enabled": True})

    def _handle_result(self, msg: dict):
        msg_type = msg.get("type")
        if msg_type == "task_result":
            self._handle_task_result(msg)
        elif msg_type == "fix_result":
            self._handle_fix_result(msg)
        elif msg_type == "scale_result":
            self._handle_scale_result(msg)

    def _handle_user_request(self, msg: dict):
        request_id = msg.get("request_id")
        text = msg.get("text", "")
        self._process_user_text(request_id, text)

    def _process_user_text(self, request_id: str, text: str):
        from tool_registry import get_declarations
        from llm_client import ask_agent

        tool = get_declarations()
        if not tool:
            ask_agent(text)
            self.publish_response({"type": "user_response", "request_id": request_id, "text": "[llm] processed"})
            return

        try:
            from google import genai  # type: ignore[import-not-found]
            from google.genai import types  # type: ignore[import-not-found]
        except ImportError:
            print("[error] google-genai package not installed; falling back to local LLM")
            ask_agent(text)
            self.publish_response({"type": "user_response", "request_id": request_id, "text": "[llm] processed"})
            return

        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            print("[error] GEMINI_API_KEY not set")
            self.publish_response({"type": "user_response", "request_id": request_id, "text": "[error] GEMINI_API_KEY not set"})
            return

        client = genai.Client(api_key=api_key)
        tool_decl = types.Tool(function_declarations=[types.FunctionDeclaration(**d) for d in tool])

        response = _generate_with_timeout(
            client.models.generate_content,
            model=get_settings().get("llm_model", "gemini-flash-latest"),
            contents=text,
            config=types.GenerateContentConfig(tools=[tool_decl]),
        )

        parts = response.candidates[0].content.parts or []
        had_function_call = False
        for part in parts:
            if part.function_call:
                had_function_call = True
                name = part.function_call.name
                args = dict(part.function_call.args)
                is_research = name in ("research_topic", "research_topic_browser", "create_skill_from_research")
                worker = self._pick_research_worker() if is_research else self._pick_worker()
                if worker:
                    self.send(
                        {
                            "type": "task_assign",
                            "task_id": f"{request_id}_{int(time.time())}",
                            "worker_id": worker,
                            "tool_name": name,
                            "args": args,
                        }
                    )
                    self.publish_response({"type": "user_response", "request_id": request_id, "text": f"[llm] calling {name}..."})
                else:
                    self.publish_response({"type": "user_response", "request_id": request_id, "text": f"[llm] no available worker for {name}"})
            elif part.text:
                print(f"[llm] {part.text}")
                self.publish_response({"type": "user_response", "request_id": request_id, "text": part.text})

        if not had_function_call:
            self._maybe_offer_skill_creation(request_id, text)

    def _maybe_offer_skill_creation(self, request_id: str, text: str):
        """Called when the LLM had no matching tool to call. Distinguishes a
        genuine capability gap (offer to build a skill) from ordinary
        conversation (say nothing) using two cheap, local heuristics -- no
        existing skill matches the topic, and the message reads like a
        request for help with something, not small talk. This is a
        deliberately simple heuristic, not a certainty."""
        settings = get_settings()
        if not settings.get("skill_gap_detection", True):
            return

        if len(text.split()) < 3:
            return  # too short to be a real capability request ("hi", "thanks")

        from skills_manager import match_skills

        if match_skills(text):
            return  # an existing skill already covers this topic

        approved = self.request_user_approval(
            "create_skill_from_research", {"topic": text}
        )
        if not approved:
            return

        worker = self._pick_research_worker()
        if not worker:
            self.publish_response(
                {
                    "type": "user_response",
                    "request_id": request_id,
                    "text": "[skill_gap] No research worker available to build the skill right now.",
                }
            )
            return

        self.send(
            {
                "type": "task_assign",
                "task_id": f"{request_id}_skill_{int(time.time())}",
                "worker_id": worker,
                "tool_name": "create_skill_from_research",
                "args": {"topic": text},
            }
        )
        self.publish_response(
            {
                "type": "user_response",
                "request_id": request_id,
                "text": f"[llm] No skill covers this yet -- researching '{text}' to build one...",
            }
        )

    def _pick_worker(self) -> str:
        available = [wid for wid, w in self.workers.items() if w.current_task is None]
        if not available:
            return None
        worker_id = available[self._round_robin % len(available)]
        self._round_robin += 1
        return worker_id

    def _pick_research_worker(self) -> str:
        available = [wid for wid, w in self.research_workers.items() if w.current_task is None]
        if not available:
            return None
        worker_id = available[self._round_robin % len(available)]
        self._round_robin += 1
        return worker_id

    def _handle_task_result(self, msg: dict):
        task_id = msg.get("task_id")
        with self._lock:
            self.task_results[task_id] = msg
        status = msg.get("status", "unknown")
        result = msg.get("result", "")
        print(f"[result] Task {task_id} {status}: {result}")

    def _handle_fix_result(self, msg: dict):
        fix_id = msg.get("fix_id")
        with self._lock:
            self.fix_results[fix_id] = msg
        worker_id = msg.get("worker_id", "?")
        results = msg.get("results", [])
        print(f"[fix] Worker {worker_id} fix completed: {results}")

    def _handle_scale_result(self, msg: dict):
        scale_id = msg.get("scale_id")
        with self._lock:
            self.scale_results[scale_id] = msg
        print(f"[scale] {scale_id} completed: {msg.get('results', [])}")

    def _handle_worker_health(self, msg: dict):
        worker_id = msg.get("worker_id")
        if worker_id in self.workers:
            self.workers[worker_id].last_heartbeat = time.time()
        elif worker_id in self.research_workers:
            self.research_workers[worker_id].last_heartbeat = time.time()

    def _handle_fixer_health(self, msg: dict):
        fixer_id = msg.get("fixer_id")
        if fixer_id in self.fixers:
            self.fixers[fixer_id].last_heartbeat = time.time()

    def _health_loop(self):
        while self.running:
            time.sleep(30)
            dead_workers = []
            for wid, worker in {**self.workers, **self.research_workers}.items():
                if time.time() - worker.last_heartbeat > 60:
                    dead_workers.append(wid)
            for wid in dead_workers:
                self._dispatch_fix(wid)

    def _dispatch_fix(self, worker_id: str):
        fixer_ids = list(self.fixers.keys())
        if not fixer_ids:
            return
        fixer_id = fixer_ids[0]
        checklist = [{"action": "restart", "worker_id": worker_id}]
        self.send(
            {
                "type": "fix_assign",
                "fix_id": f"fix_{worker_id}_{int(time.time())}",
                "fixer_id": fixer_id,
                "worker_id": worker_id,
                "steps": checklist,
            }
        )

    def _scale_down_loop(self):
        while self.running:
            time.sleep(300)
            now = time.time()
            with self._lock:
                to_remove = []
                for wid, worker in self.workers.items():
                    if wid.startswith("worker_") and int(wid.split("_")[1]) >= self.baseline_workers:
                        if now - getattr(worker, "last_heartbeat", now) > self.idle_grace:
                            to_remove.append(wid)
                for wid in to_remove:
                    self.workers[wid].stop()
                    del self.workers[wid]

    def request_user_approval(self, tool_name: str, args: dict) -> bool:
        from confirmation_widget import confirm_action
        return confirm_action(tool_name, args)