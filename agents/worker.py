"""
Worker agent for the AI PC Agent hierarchy.

Executes tasks assigned by the main agent and reports results back
via the ZMQ result bus.
"""
import time

from tool_registry import dispatch, get_declarations, TOOLS

from .base import BaseAgent

# Tools that require the research pipeline (search/extraction/synthesis) are
# routed to ResearchWorker instead -- regular workers never claim them, even
# via the "all registered tools" default below.
RESEARCH_ONLY_TOOLS = {"research_topic", "research_topic_browser", "create_skill_from_research"}


def _default_capabilities() -> list:
    """Every registered tool a regular Worker can run, derived live from
    tool_registry.TOOLS so this never drifts out of sync as tools are added
    or removed -- unlike the old hardcoded ["open_app", "move_file"] list,
    which didn't match anything actually in the registry."""
    return [name for name in TOOLS if name not in RESEARCH_ONLY_TOOLS]


class Worker(BaseAgent):
    def __init__(self, worker_id: str, capabilities: list = None):
        super().__init__(worker_id, "worker")
        self.capabilities = capabilities or _default_capabilities()
        self.last_heartbeat = time.time()
        self.current_task = None

    def handle(self, msg: dict):
        msg_type = msg.get("type")
        if msg_type == "task_assign":
            self._handle_task(msg)
        elif msg_type == "health_check":
            self._send_heartbeat()

    def _handle_task(self, msg: dict):
        task_id = msg.get("task_id")
        tool_name = msg.get("tool_name")
        args = msg.get("args", {})
        self.current_task = task_id

        if tool_name not in self.capabilities:
            self.send_result(
                {
                    "type": "task_result",
                    "task_id": task_id,
                    "status": "error",
                    "result": f"Worker {self.agent_id} cannot handle tool {tool_name}",
                }
            )
            self.current_task = None
            return

        try:
            result = dispatch(tool_name, args)
            self.send_result(
                {
                    "type": "task_result",
                    "task_id": task_id,
                    "status": "success",
                    "result": result,
                }
            )
        except Exception as e:
            self.send_result(
                {
                    "type": "task_result",
                    "task_id": task_id,
                    "status": "error",
                    "result": str(e),
                }
            )
        self.current_task = None

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