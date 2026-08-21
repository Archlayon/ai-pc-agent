"""
Folder-watch automation for the AI PC Agent.

Uses watchdog for real-time inotify-based file system events on Linux.
"""
import json
import os
import threading
from datetime import datetime, timezone

from audit_log import log_action

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler

    WATCHDOG_AVAILABLE = True

    class _WatchHandler(FileSystemEventHandler):
        def __init__(self, callback):
            self.callback = callback

        def on_created(self, event):
            if not event.is_directory:
                self.callback(event.src_path, "created")

        def on_modified(self, event):
            if not event.is_directory:
                self.callback(event.src_path, "modified")
except ImportError:
    WATCHDOG_AVAILABLE = False
    Observer = None

    class _WatchHandler:
        def __init__(self, callback):
            self.callback = callback


WATCH_STATE_PATH = os.path.expanduser("~/.local/share/ai-pc-agent/watch_state.json")


class FolderWatcher:
    def __init__(self):
        self.watches = {}
        self.observer = None
        self._load_state()

    def _load_state(self):
        if not os.path.exists(WATCH_STATE_PATH):
            return
        try:
            with open(WATCH_STATE_PATH, "r") as f:
                data = json.load(f)
                self.watches = data.get("watches", {})
        except Exception:
            pass

    def _save_state(self):
        try:
            with open(WATCH_STATE_PATH, "w") as f:
                json.dump({"watches": self.watches}, f, indent=2)
        except Exception:
            pass

    def _on_event(self, filepath: str, trigger: str):
        for folder, config in self.watches.items():
            if filepath.startswith(folder) and config.get("trigger") == trigger:
                action = config.get("action", "")
                print(f"[watch] {trigger}: {filepath} -> {action}")

    def start(self):
        if not WATCHDOG_AVAILABLE or not self.watches:
            return
        self.observer = Observer()
        for folder in self.watches:
            if os.path.isdir(folder):
                handler = _WatchHandler(self._on_event)
                self.observer.schedule(handler, folder, recursive=False)
        self.observer.start()

    def stop(self):
        if self.observer:
            self.observer.stop()
            self.observer.join(timeout=2)

    def add_watch(self, folder: str, action: str, trigger: str = "created"):
        folder = os.path.expanduser(folder)
        self.watches[folder] = {"action": action, "trigger": trigger, "added_at": datetime.now(timezone.utc).isoformat()}
        self._save_state()
        log_action("folder_watch_add", {"folder": folder, "action": action}, "approved", f"Watching {folder}")

        if WATCHDOG_AVAILABLE and os.path.isdir(folder):
            if self.observer is None:
                self.observer = Observer()
            handler = _WatchHandler(self._on_event)
            self.observer.schedule(handler, folder, recursive=False)
            if not self.observer.is_alive():
                self.observer.start()

    def remove_watch(self, folder: str):
        folder = os.path.expanduser(folder)
        if folder in self.watches:
            del self.watches[folder]
            self._save_state()
            log_action("folder_watch_remove", {"folder": folder}, "approved", f"Stopped watching {folder}")

    def get_watches(self):
        return dict(self.watches)


folder_watcher = FolderWatcher()


def add_folder_watch(folder: str, action: str, trigger: str = "created") -> str:
    folder_watcher.add_watch(folder, action, trigger)
    return f"Watching {folder} for {trigger} -> {action}"


def remove_folder_watch(folder: str) -> str:
    folder_watcher.remove_watch(folder)
    return f"Stopped watching {folder}"


def list_folder_watches() -> str:
    watches = folder_watcher.get_watches()
    if not watches:
        return "No active folder watches."
    lines = [f"{folder}: {config['action']} ({config['trigger']})" for folder, config in watches.items()]
    return "\n".join(lines)
