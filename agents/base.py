"""
Base agent class for the AI PC Agent hierarchy.

Provides common ZMQ bus integration, message handling, and lifecycle.
"""
import threading
import time
from abc import ABC, abstractmethod

from zmq_bus import AgentBus


class BaseAgent(ABC):
    def __init__(self, agent_id: str, role: str):
        self.agent_id = agent_id
        self.role = role
        self.bus = AgentBus(role)
        self.running = False
        self._thread = None
        self.last_heartbeat = time.time()

    def start(self):
        self.running = True
        self.bus._handle = self._on_message
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        self.bus.start()
        while self.running:
            time.sleep(0.1)
        self.bus.stop()

    def _on_message(self, msg: dict):
        msg_type = msg.get("type")
        if msg_type == "shutdown":
            self.running = False
        else:
            self.handle(msg)

    @abstractmethod
    def handle(self, msg: dict):
        pass

    def send(self, msg: dict):
        msg["from"] = self.agent_id
        msg["ts"] = time.time()
        self.bus.publish(msg)

    def send_result(self, msg: dict):
        msg["from"] = self.agent_id
        msg["ts"] = time.time()
        self.bus.send_result(msg)

    def publish_response(self, msg: dict):
        msg["from"] = self.agent_id
        msg["ts"] = time.time()
        self.bus.publish_response(msg)

    def stop(self):
        self.running = False
