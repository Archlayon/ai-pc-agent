"""
Settings management for the AI PC Agent.

Stores config in ~/.config/ai-pc-agent/config.json
"""
import json
import os

CONFIG_DIR = os.path.expanduser("~/.config/ai-pc-agent")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")

DEFAULTS = {
    "autonomy_mode": False,
    "voice_mode": False,
    "gui_confirm": True,
    "hotkey": "Control+l",
    "watch_folders": [],
    "enabled_modules": [],
    "whisper_model": "small",
    "llm_model": "gemini-flash-latest",
    "confirm_gate": True,
    "max_workers": 3,
    "max_fixers": 2,
    "idle_grace_seconds": 3600,
}


def _ensure_config():
    os.makedirs(CONFIG_DIR, exist_ok=True)
    if not os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "w") as f:
            json.dump(DEFAULTS, f, indent=2)
    return CONFIG_PATH


def get_settings():
    _ensure_config()
    with open(CONFIG_PATH, "r") as f:
        settings = json.load(f)
    for k, v in DEFAULTS.items():
        settings.setdefault(k, v)
    return settings


def update_settings(patch: dict):
    settings = get_settings()
    settings.update(patch)
    with open(CONFIG_PATH, "w") as f:
        json.dump(settings, f, indent=2)
    return settings
