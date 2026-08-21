"""
System tray daemon for the AI PC Agent.

Provides a background always-on-top presence with menu actions.
"""
import os
import threading

import pystray
from PIL import Image, ImageDraw

from hotkey_listener import main as hotkey_main, set_main_agent, set_widget
from supervisor import Supervisor
from main_widget import AgentWidget
from settings_panel import SettingsPanel

_hotkey_thread = None
_supervisor = None
_widget = None
_settings_panel = None


def _create_icon():
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((8, 8, size - 8, size - 8), fill=(0, 120, 215, 255))
    draw.ellipse((20, 20, size - 20, size - 20), fill=(255, 255, 255, 255))
    return img


def _start_hotkey():
    global _hotkey_thread
    if _hotkey_thread and _hotkey_thread.is_alive():
        return
    _hotkey_thread = threading.Thread(target=hotkey_main, daemon=True)
    _hotkey_thread.start()


def _start_supervisor():
    global _supervisor
    if _supervisor is not None:
        return
    _supervisor = Supervisor()
    _supervisor.start()
    set_main_agent(_supervisor.main_agent)


def _show_widget():
    import subprocess
    subprocess.Popen(["python3", "-m", "main_widget"], cwd="/home/layon/ai-pc-agent")


def _show_settings():
    import subprocess
    subprocess.Popen(["python3", "-m", "settings_panel"], cwd="/home/layon/ai-pc-agent")


def run_tray():
    _start_supervisor()
    _start_hotkey()

    icon = pystray.Icon("ai-pc-agent", _create_icon(), "AI PC Agent")

    icon.menu = pystray.Menu(
        pystray.MenuItem("Show Widget", lambda icon, item: _show_widget()),
        pystray.MenuItem("Settings", lambda icon, item: _show_settings()),
        pystray.MenuItem("Quit", lambda icon, item: _on_quit(icon)),
    )
    icon.run()


def _on_quit(icon):
    global _supervisor
    if _supervisor:
        _supervisor.stop()
    icon.stop()
    os._exit(0)


if __name__ == "__main__":
    run_tray()
