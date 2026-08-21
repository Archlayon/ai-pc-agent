"""
ZeroMQ-based inter-agent communication layer.

Uses a multi-socket pattern:
- Command bus: main agent PUB -> workers/fixers SUB (broadcast commands)
- Result bus: workers/fixers PUSH -> main agent PULL (unicast results)
- Input bus: widget PUSH -> main agent PULL (user input from GUI)
- Response bus: main agent PUB -> widget SUB (responses to GUI)
"""
import json
import os
import threading

import zmq

BUS_DIR = os.path.expanduser("~/.local/share/ai-pc-agent")
CMD_ENDPOINT = f"ipc://{BUS_DIR}/cmd.ipc"
RESULT_ENDPOINT = f"ipc://{BUS_DIR}/results.ipc"
INPUT_ENDPOINT = f"ipc://{BUS_DIR}/input.ipc"
RESPONSE_ENDPOINT = f"ipc://{BUS_DIR}/response.ipc"


def _ensure_bus_dir():
    os.makedirs(BUS_DIR, exist_ok=True)


class AgentBus:
    def __init__(self, role: str):
        _ensure_bus_dir()
        self.role = role
        self.context = zmq.Context()

        if role == "main":
            self.cmd_socket = self.context.socket(zmq.PUB)
            self.cmd_socket.bind(CMD_ENDPOINT)
            self.result_socket = self.context.socket(zmq.PULL)
            self.result_socket.bind(RESULT_ENDPOINT)
            self.input_socket = self.context.socket(zmq.PULL)
            self.input_socket.bind(INPUT_ENDPOINT)
            self.response_socket = self.context.socket(zmq.PUB)
            self.response_socket.bind(RESPONSE_ENDPOINT)
            self._socket = self.cmd_socket
        else:
            self.cmd_socket = self.context.socket(zmq.SUB)
            self.cmd_socket.connect(CMD_ENDPOINT)
            self.cmd_socket.setsockopt_string(zmq.SUBSCRIBE, "")
            self.result_socket = self.context.socket(zmq.PUSH)
            self.result_socket.connect(RESULT_ENDPOINT)
            self._socket = self.cmd_socket

        self._running = False
        self._thread = None
        self._handle = lambda msg: None

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self):
        while self._running:
            try:
                msg = self.cmd_socket.recv_json(flags=zmq.NOBLOCK)
                self._handle(msg)
            except zmq.Again:
                continue
            except Exception:
                continue

    def publish(self, msg: dict):
        self.cmd_socket.send_json(msg)

    def publish_response(self, msg: dict):
        self.response_socket.send_json(msg)

    def send_result(self, msg: dict):
        self.result_socket.send_json(msg)

    def recv_result(self, timeout_ms: int = 1000) -> dict:
        self.result_socket.setsockopt(zmq.RCVTIMEO, timeout_ms)
        try:
            return self.result_socket.recv_json()
        except zmq.Again:
            return None
        finally:
            self.result_socket.setsockopt(zmq.RCVTIMEO, -1)

    def recv_input(self, timeout_ms: int = 500) -> dict:
        if self.role != "main":
            return None
        self.input_socket.setsockopt(zmq.RCVTIMEO, timeout_ms)
        try:
            return self.input_socket.recv_json()
        except zmq.Again:
            return None
        finally:
            self.input_socket.setsockopt(zmq.RCVTIMEO, -1)

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
        self.cmd_socket.close()
        if hasattr(self, 'result_socket'):
            self.result_socket.close()
        if hasattr(self, 'input_socket'):
            self.input_socket.close()
        if hasattr(self, 'response_socket'):
            self.response_socket.close()
        self.context.term()
