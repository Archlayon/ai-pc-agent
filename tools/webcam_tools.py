"""
Webcam tools for the AI PC Agent.

Strictly on-demand only — never runs silently in the background.
"""
import os
import uuid
from datetime import datetime, timezone

from audit_log import log_action

CAPTURES_DIR = os.path.expanduser("~/.local/share/ai-pc-agent/captures")


def _ensure_captures_dir():
    os.makedirs(CAPTURES_DIR, exist_ok=True)


def capture_webcam(filename: str = "") -> str:
    _ensure_captures_dir()
    try:
        import cv2

        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            return "[error] Could not open webcam"

        ret, frame = cap.read()
        cap.release()

        if not ret:
            return "[error] Failed to capture frame from webcam"

        if not filename:
            filename = f"capture_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}.png"

        filepath = os.path.join(CAPTURES_DIR, filename)
        cv2.imwrite(filepath, frame)
        log_action("capture_webcam", {"filename": filename}, "approved", f"Saved to {filepath}")
        return f"Webcam capture saved to {filepath}"
    except ImportError:
        return "[error] opencv-python is not installed. Install it to use webcam capture."
    except Exception as e:
        return f"[error] Webcam capture failed: {e}"


def list_captures() -> str:
    _ensure_captures_dir()
    files = sorted(os.listdir(CAPTURES_DIR))
    if not files:
        return "No captures found."
    return "\n".join(files)
