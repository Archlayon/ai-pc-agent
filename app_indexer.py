"""
Lightweight PC app indexer for the AI PC Agent.

Scans the filesystem for applications, builds a persistent search index,
and provides fuzzy name matching so "chrome" finds "google-chrome",
"chromium-browser", etc.

Index is stored in ~/.local/share/ai-pc-agent/app_index.json and
refreshed in the background when stale.
"""
import json
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

APP_INDEX_PATH = os.path.expanduser("~/.local/share/ai-pc-agent/app_index.json")
INDEX_TTL = 86400
SCAN_DIRS = [
    "/usr/bin",
    "/usr/local/bin",
    "/bin",
    "/usr/sbin",
    "/usr/local/sbin",
    "/snap/bin",
    "/opt",
    os.path.expanduser("~/.local/bin"),
    "/usr/share/applications",
    os.path.expanduser("~/.local/share/applications"),
    "/var/lib/flatpak/exports/share/applications",
    "/var/lib/snapd/desktop/applications",
    os.path.expanduser("~/Applications"),
]
NAME_ALIASES = {
    "chrome": ["google-chrome", "chromium-browser", "chromium", "chrome"],
    "google chrome": ["google-chrome", "chromium-browser"],
    "firefox": ["firefox", "mozilla-firefox"],
    "blender": ["blender"],
    "vscode": ["code", "visual-studio-code", "vscode"],
    "visual studio code": ["code", "visual-studio-code"],
    "discord": ["discord"],
    "spotify": ["spotify"],
    "steam": ["steam"],
    "vlc": ["vlc", "vlc-media-player"],
    "libreoffice": ["libreoffice", "libreoffice-writer", "libreoffice-calc"],
    "terminal": ["gnome-terminal", "konsole", "xfce4-terminal", "terminal"],
    "files": ["nautilus", "dolphin", "thunar", "nemo", "pcmanfm"],
    "calculator": ["gnome-calculator", "kcalc", "xfce4-calculator"],
    "settings": ["gnome-control-center", "systemsettings", "xfce4-settings"],
    "text editor": ["gedit", "kate", "mousepad", "xfce4-terminal", "nano"],
    "gedit": ["gedit"],
    "kate": ["kate"],
    "nano": ["nano"],
    "vim": ["vim"],
    "code": ["code", "visual-studio-code"],
    "obs": ["obs", "obs-studio"],
    "obs studio": ["obs", "obs-studio"],
    "gimp": ["gimp"],
    "inkscape": ["inkscape"],
    "audacity": ["audacity"],
    "telegram": ["telegram-desktop", "telegram"],
    "whatsapp": ["whatsapp", "whatsie"],
    "zoom": ["zoom"],
    "skype": ["skype"],
    "microsoft teams": ["teams", "microsoft-teams"],
    "teams": ["teams", "microsoft-teams"],
    "slack": ["slack"],
    "notion": ["notion", "notion-app"],
    "figma": ["figma"],
    "canva": ["canva"],
    "postman": ["postman"],
    "docker": ["docker"],
    "virtualbox": ["virtualbox"],
    "vmware": ["vmware"],
    "wine": ["wine"],
}


def _ensure_dirs():
    os.makedirs(os.path.dirname(APP_INDEX_PATH), exist_ok=True)


def _load_index():
    _ensure_dirs()
    if not os.path.exists(APP_INDEX_PATH):
        return None
    try:
        with open(APP_INDEX_PATH, "r") as f:
            data = json.load(f)
        if time.time() - data.get("timestamp", 0) < INDEX_TTL:
            return data.get("apps", [])
    except Exception:
        pass
    return None


def _save_index(apps):
    _ensure_dirs()
    data = {
        "timestamp": time.time(),
        "apps": apps,
    }
    with open(APP_INDEX_PATH, "w") as f:
        json.dump(data, f, indent=2)


def _scan_desktop_files():
    apps = []
    seen = set()
    for d in SCAN_DIRS:
        if not os.path.isdir(d):
            continue
        for root, dirs, files in os.walk(d):
            for f in files:
                if not f.endswith(".desktop"):
                    continue
                full = os.path.join(root, f)
                if full in seen:
                    continue
                seen.add(full)
                try:
                    with open(full, "r", errors="ignore") as fh:
                        content = fh.read()
                    name = f.replace(".desktop", "").lower()
                    exec_line = None
                    for line in content.splitlines():
                        if line.strip().startswith("Exec="):
                            exec_line = line.strip()[5:].strip()
                            break
                    if exec_line:
                        parts = exec_line.split()
                        cmd = parts[0].lower() if parts else ""
                        flatpak_id = None
                        if cmd == "/usr/bin/flatpak" or cmd == "flatpak":
                            found_run = False
                            for part in parts[1:]:
                                if part == "run":
                                    found_run = True
                                    continue
                                if found_run and not part.startswith("--"):
                                    flatpak_id = part
                                    break
                        apps.append({
                            "name": name,
                            "exec": cmd,
                            "exec_line": exec_line,
                            "path": full,
                            "type": "desktop",
                            "flatpak_id": flatpak_id,
                        })
                except Exception:
                    pass
            break
    return apps


def _scan_binaries():
    apps = []
    seen = set()
    for d in SCAN_DIRS:
        if not os.path.isdir(d):
            continue
        try:
            for entry in os.listdir(d):
                full = os.path.join(d, entry)
                if not os.path.isfile(full):
                    continue
                if full in seen:
                    continue
                seen.add(full)
                if os.access(full, os.X_OK):
                    apps.append({
                        "name": entry.lower(),
                        "exec": entry.lower(),
                        "exec_line": entry,
                        "path": full,
                        "type": "binary",
                    })
        except Exception:
            pass
    return apps


def _build_index(force=False):
    cached = None if force else _load_index()
    if cached is not None:
        return cached

    apps = _scan_desktop_files()
    apps += _scan_binaries()

    seen = set()
    unique = []
    for a in apps:
        key = (a["exec"], a["path"])
        if key not in seen:
            seen.add(key)
            unique.append(a)

    _save_index(unique)
    return unique


def _fuzzy_match(query, apps):
    q = query.lower().strip()
    if not q:
        return []

    alias_targets = NAME_ALIASES.get(q, [q])
    all_targets = set(alias_targets + [q])

    results = []
    for app in apps:
        name = app.get("name", "")
        exec_name = app.get("exec", "")
        flatpak_id = app.get("flatpak_id", "")
        score = 0

        if q == name or q == exec_name or q == flatpak_id:
            score = 100
        elif name.startswith(q) or exec_name.startswith(q) or (flatpak_id and flatpak_id.startswith(q)):
            score = 80
        elif q in name or q in exec_name or (flatpak_id and q in flatpak_id):
            score = 60
        elif name in all_targets or exec_name in all_targets or flatpak_id in all_targets:
            score = 90
        else:
            for target in all_targets:
                if target in name or target in exec_name or (flatpak_id and target in flatpak_id):
                    score = max(score, 70)
                elif name.startswith(target) or exec_name.startswith(target) or (flatpak_id and flatpak_id.startswith(target)):
                    score = max(score, 85)

        if score > 0:
            results.append((score, app))

    results.sort(key=lambda x: x[0], reverse=True)
    return [app for _, app in results]


def lookup_app(query):
    apps = _build_index()
    matches = _fuzzy_match(query, apps)
    return matches


def refresh_index():
    _build_index(force=True)


_index_lock = threading.Lock()
_index_building = False


def background_refresh():
    global _index_building
    with _index_lock:
        if _index_building:
            return
        _index_building = True
    try:
        _build_index(force=True)
    finally:
        with _index_lock:
            _index_building = False


def start_background_indexer():
    def _loop():
        while True:
            time.sleep(3600)
            background_refresh()
    threading.Thread(target=_loop, daemon=True).start()
