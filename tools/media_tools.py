"""
Media tools for the AI PC Agent.

Play media files and URLs.
"""
import os
import subprocess

from audit_log import log_action


def play_media(path: str) -> str:
    path = os.path.expanduser(path)
    if not os.path.exists(path):
        return f"[error] Media file not found: {path}"

    try:
        subprocess.Popen(["xdg-open", path])
        log_action("play_media", {"path": path}, "approved", f"Playing {path}")
        return f"Playing {path}"
    except Exception as e:
        return f"[error] Failed to play media: {e}"
