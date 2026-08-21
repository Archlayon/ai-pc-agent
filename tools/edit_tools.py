"""
Edit files tool for the AI PC Agent.

Supports reading, writing, and appending to files.
"""
import os

from audit_log import log_action


def read_file(path: str) -> str:
    path = os.path.expanduser(path)
    if not os.path.exists(path):
        return f"[error] File not found: {path}"
    try:
        with open(path, "r") as f:
            content = f.read()
        log_action("read_file", {"path": path}, "approved", f"Read {len(content)} bytes")
        return content
    except Exception as e:
        return f"[error] Failed to read file: {e}"


def write_file(path: str, content: str) -> str:
    path = os.path.expanduser(path)
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w") as f:
            f.write(content)
        log_action("write_file", {"path": path, "bytes": len(content)}, "approved", f"Wrote {len(content)} bytes")
        return f"Wrote {len(content)} bytes to {path}"
    except Exception as e:
        return f"[error] Failed to write file: {e}"


def append_file(path: str, content: str) -> str:
    path = os.path.expanduser(path)
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "a") as f:
            f.write(content)
        log_action("append_file", {"path": path, "bytes": len(content)}, "approved", f"Appended {len(content)} bytes")
        return f"Appended {len(content)} bytes to {path}"
    except Exception as e:
        return f"[error] Failed to append file: {e}"


def edit_file_line(path: str, line_number: int, new_text: str) -> str:
    path = os.path.expanduser(path)
    if not os.path.exists(path):
        return f"[error] File not found: {path}"
    try:
        with open(path, "r") as f:
            lines = f.readlines()
        if line_number < 1 or line_number > len(lines):
            return f"[error] Line {line_number} out of range (file has {len(lines)} lines)"
        lines[line_number - 1] = new_text + "\n"
        with open(path, "w") as f:
            f.writelines(lines)
        log_action("edit_file_line", {"path": path, "line": line_number}, "approved", f"Edited line {line_number}")
        return f"Updated line {line_number} in {path}"
    except Exception as e:
        return f"[error] Failed to edit file: {e}"
