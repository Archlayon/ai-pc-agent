"""
Monitor PC state tool for the AI PC Agent.

Reports CPU, memory, disk, and battery status.
"""
import shutil

from audit_log import log_action

try:
    import psutil

    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False


def _check_psutil() -> str:
    if not PSUTIL_AVAILABLE:
        return "[error] psutil is not installed. Install it to use PC monitoring."
    return None


def get_cpu_usage() -> str:
    err = _check_psutil()
    if err:
        return err
    try:
        cpu = psutil.cpu_percent(interval=1)
        log_action("get_cpu_usage", {}, "approved", f"CPU usage: {cpu}%")
        return f"CPU usage: {cpu}%"
    except Exception as e:
        return f"[error] Failed to get CPU usage: {e}"


def get_memory_usage() -> str:
    err = _check_psutil()
    if err:
        return err
    try:
        mem = psutil.virtual_memory()
        log_action("get_memory_usage", {}, "approved", f"Memory: {mem.percent}% used ({mem.used // (1024*1024)}MB / {mem.total // (1024*1024)}MB)")
        return f"Memory: {mem.percent}% used ({mem.used // (1024*1024)}MB / {mem.total // (1024*1024)}MB)"
    except Exception as e:
        return f"[error] Failed to get memory usage: {e}"


def get_disk_usage(path: str = "/") -> str:
    err = _check_psutil()
    if err:
        return err
    try:
        disk = psutil.disk_usage(path)
        log_action("get_disk_usage", {"path": path}, "approved", f"Disk {path}: {disk.percent}% used ({disk.used // (1024*1024*1024)}GB / {disk.total // (1024*1024*1024)}GB)")
        return f"Disk {path}: {disk.percent}% used ({disk.used // (1024*1024*1024)}GB / {disk.total // (1024*1024*1024)}GB)"
    except Exception as e:
        return f"[error] Failed to get disk usage: {e}"


def get_battery_status() -> str:
    err = _check_psutil()
    if err:
        return err
    try:
        battery = psutil.sensors_battery()
        if battery is None:
            return "No battery detected (desktop or unknown battery)."
        status = "Charging" if battery.power_plugged else "Discharging"
        log_action("get_battery_status", {}, "approved", f"Battery: {battery.percent}% ({status})")
        return f"Battery: {battery.percent}% ({status})"
    except Exception as e:
        return f"[error] Failed to get battery status: {e}"


def get_full_pc_state() -> str:
    err = _check_psutil()
    if err:
        return err
    try:
        cpu = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        battery = psutil.sensors_battery()

        lines = [
            f"CPU: {cpu}%",
            f"Memory: {mem.percent}% ({mem.used // (1024*1024)}MB / {mem.total // (1024*1024)}MB)",
            f"Disk /: {disk.percent}% ({disk.used // (1024*1024*1024)}GB / {disk.total // (1024*1024*1024)}GB)",
        ]
        if battery:
            status = "Charging" if battery.power_plugged else "Discharging"
            lines.append(f"Battery: {battery.percent}% ({status})")
        else:
            lines.append("Battery: No battery detected")

        result = "\n".join(lines)
        log_action("get_full_pc_state", {}, "approved", result)
        return result
    except Exception as e:
        return f"[error] Failed to get PC state: {e}"
