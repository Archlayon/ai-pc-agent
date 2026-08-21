"""
Research worker agent for the AI PC Agent hierarchy.

Specialized worker for web search and multi-source synthesis tasks.
Double-checks another worker's output before it goes back to the main agent.
"""
import time

from tool_registry import dispatch

from .base import BaseAgent

RESEARCH_TOOLS = {"research_topic", "research_topic_browser"}
FALLBACK_TOOL = "research_topic_browser"


def _looks_like_failure(result) -> bool:
    if not isinstance(result, str) or not result.strip():
        return True
    lowered = result.strip().lower()
    return lowered.startswith("[error]") or lowered.startswith("no usable sources")


class ResearchWorker(BaseAgent):
    def __init__(self, worker_id: str):
        super().__init__(worker_id, "research_worker")
        self.capabilities = list(RESEARCH_TOOLS)
        self.last_heartbeat = time.time()
        self.current_task = None

    def handle(self, msg: dict):
        msg_type = msg.get("type")
        if msg_type == "task_assign":
            self._handle_task(msg)
        elif msg_type == "health_check":
            self._send_heartbeat()
        elif msg_type == "verify_request":
            self._handle_verify(msg)

    def _handle_task(self, msg: dict):
        task_id = msg.get("task_id")
        tool_name = msg.get("tool_name", "research_topic")
        args = msg.get("args", {})
        self.current_task = task_id

        if tool_name not in self.capabilities:
            self.send_result(
                {
                    "type": "task_result",
                    "task_id": task_id,
                    "status": "error",
                    "result": f"Research worker {self.agent_id} cannot handle tool {tool_name}",
                }
            )
            self.current_task = None
            return

        if not args.get("topic"):
            self.send_result(
                {
                    "type": "task_result",
                    "task_id": task_id,
                    "status": "error",
                    "result": "No topic provided for research",
                }
            )
            self.current_task = None
            return

        try:
            result = dispatch(tool_name, args)
        except Exception as e:
            result = f"[error] {tool_name} raised an exception: {e}"

        status = "success"

        if tool_name == "research_topic" and _looks_like_failure(result):
            print(f"[research_worker] {tool_name} failed for '{args.get('topic')}', falling back to {FALLBACK_TOOL}")
            try:
                fallback_result = dispatch(FALLBACK_TOOL, args)
            except Exception as e:
                fallback_result = f"[error] {FALLBACK_TOOL} raised an exception: {e}"

            if not _looks_like_failure(fallback_result):
                result = fallback_result
            else:
                result = (
                    f"Both research_topic and {FALLBACK_TOOL} failed.\n"
                    f"research_topic: {result}\n"
                    f"{FALLBACK_TOOL}: {fallback_result}"
                )
                status = "error"
        elif _looks_like_failure(result):
            status = "error"

        self.send_result(
            {
                "type": "task_result",
                "task_id": task_id,
                "status": status,
                "result": result,
            }
        )
        self.current_task = None

    def _handle_verify(self, msg: dict):
        verify_id = msg.get("verify_id")
        original_result = msg.get("original_result", "")
        self.send_result(
            {
                "type": "verify_result",
                "verify_id": verify_id,
                "status": "verified",
                "result": f"Verified research output: {original_result[:200]}...",
            }
        )

    def _send_heartbeat(self):
        self.send(
            {
                "type": "worker_health",
                "worker_id": self.agent_id,
                "status": "alive",
                "current_task": self.current_task,
                "last_heartbeat": time.time(),
            }
        )