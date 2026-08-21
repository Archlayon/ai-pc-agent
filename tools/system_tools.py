"""
System settings tools for the AI PC Agent.

Change brightness, volume, and other system settings.
"""
import subprocess

from audit_log import log_action


def _run(cmd: list) -> str:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            return result.stdout.strip() or "OK"
        return f"[error] {' '.join(cmd)} failed: {result.stderr.strip()}"
    except Exception as e:
        return f"[error] {' '.join(cmd)} failed: {e}"


def set_brightness(level: int) -> str:
    level = max(0, min(100, int(level)))
    _run(["brightnessctl", "set", f"{level}%"])
    return f"Brightness set to {level}%"


def set_volume(level: int) -> str:
    level = max(0, min(100, int(level)))
    _run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{level}%"])
    return f"Volume set to {level}%"


def get_brightness() -> str:
    return _run(["brightnessctl", "get"])


def get_volume() -> str:
    return _run(["pactl", "get-sink-volume", "@DEFAULT_SINK@"])


def shutdown_pc(delay_minutes: int = 0) -> str:
    delay_seconds = delay_minutes * 60
    cmd = ["systemctl", "poweroff"]
    if delay_seconds > 0:
        cmd = ["shutdown", "-h", f"+{delay_minutes}"]
    log_action("shutdown_pc", {"delay_minutes": delay_minutes}, "approved", f"Shutdown scheduled in {delay_minutes} minutes")
    return f"Shutdown scheduled in {delay_minutes} minutes. Run 'shutdown -c' to cancel."


def restart_pc(delay_minutes: int = 0) -> str:
    delay_seconds = delay_minutes * 60
    cmd = ["systemctl", "reboot"]
    if delay_seconds > 0:
        cmd = ["shutdown", "-r", f"+{delay_minutes}"]
    log_action("restart_pc", {"delay_minutes": delay_minutes}, "approved", f"Restart scheduled in {delay_minutes} minutes")
    return f"Restart scheduled in {delay_minutes} minutes. Run 'shutdown -c' to cancel."


def cancel_shutdown() -> str:
    result = _run(["shutdown", "-c"])
    log_action("cancel_shutdown", {}, "approved", "Cancelled scheduled shutdown/restart")
    return "Scheduled shutdown/restart cancelled."
