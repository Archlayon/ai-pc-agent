"""
Tool registry + dispatcher for the AI PC Agent.

Logs every action attempt to the audit log. Respects settings for autonomy
mode and confirmation gating. Uses GUI confirmation widget when available.
"""
import os
import re
import shutil
import subprocess

from audit_log import log_action
from confirmation_widget import confirm_action
from settings import get_settings
from tools.download_tools import download_file
from tools.edit_tools import append_file, edit_file_line, read_file, write_file
from tools.email_tools import draft_email, list_drafts
from tools.folder_watch import add_folder_watch, list_folder_watches, remove_folder_watch
from tools.gimp_tools import gimp_batch_operation
from tools.media_tools import play_media
from tools.monitor_tools import get_battery_status, get_cpu_usage, get_disk_usage, get_full_pc_state, get_memory_usage
from tools.research_tools import research_topic
from tools.skill_creator import create_skill_from_research
from tools.gimp_designer import design_with_gimp
from browser_research import research_topic_browser
from tools.system_tools import cancel_shutdown, get_brightness, get_volume, restart_pc, set_brightness, set_volume, shutdown_pc
from tools.webcam_tools import capture_webcam, list_captures

TIER_SAFE = 1
TIER_SENSITIVE = 2
TIER_HIGH_RISK = 3

_APP_CACHE = {}


def _normalize_app_name(name: str) -> str:
    n = name.lower().strip()
    n = re.sub(r'\s+', ' ', n)
    n = re.sub(r'^(a|an|the)(\s+|$)', '', n).strip()
    n = re.sub(r'\s+(media player|player|application|app|program|software)$', '', n).strip()
    if not n:
        return ""
    mapping = {
        'you tube': 'youtube',
        'google chrome': 'chrome',
        'chromium': 'chrome',
        'ms teams': 'teams',
        'microsoft teams': 'teams',
        'visual studio code': 'vscode',
        'vs code': 'vscode',
        'obs studio': 'obs',
        'libre office': 'libreoffice',
        'text editor': 'gedit',
        'file manager': 'files',
    }
    return mapping.get(n, n)


def _verify_process_running(keyword: str, timeout: float = 3.0) -> bool:
    try:
        import psutil
        import time
        start = time.time()
        keyword_lower = keyword.lower()

        existing_pids = set()
        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                pname = (proc.info.get("name") or "").lower()
                cmdline = " ".join(proc.info.get("cmdline") or []).lower()
                if keyword_lower in pname or keyword_lower in cmdline:
                    existing_pids.add(proc.info.get("pid"))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        time.sleep(0.5)
        while time.time() - start < timeout:
            for proc in psutil.process_iter(["pid", "name", "cmdline"]):
                try:
                    pid = proc.info.get("pid")
                    if pid in existing_pids:
                        continue
                    pname = (proc.info.get("name") or "").lower()
                    cmdline = " ".join(proc.info.get("cmdline") or []).lower()
                    if keyword_lower in pname or keyword_lower in cmdline:
                        return True
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            time.sleep(0.3)
        return False
    except ImportError:
        return True
    except Exception:
        return False


def _open_app(app_name: str) -> str:
    app_lower = _normalize_app_name(app_name)
    if not app_lower:
        return f"[error] Please specify an application name. Example: 'open firefox'"

    WEB_APPS = {
        "youtube", "whatsapp", "tiktok", "instagram", "facebook",
        "twitter", "x.com", "reddit", "linkedin", "snapchat",
        "telegram", "discord", "zoom", "messenger",
    }

    if app_lower in WEB_APPS:
        url = {
            "youtube": "https://www.youtube.com",
            "whatsapp": "https://web.whatsapp.com",
            "tiktok": "https://www.tiktok.com",
            "instagram": "https://www.instagram.com",
            "facebook": "https://www.facebook.com",
            "twitter": "https://twitter.com",
            "x.com": "https://x.com",
            "reddit": "https://www.reddit.com",
            "linkedin": "https://www.linkedin.com",
            "snapchat": "https://www.snapchat.com",
            "telegram": "https://web.telegram.org",
            "discord": "https://discord.com",
            "zoom": "https://zoom.us",
            "messenger": "https://www.messenger.com",
        }.get(app_lower, f"https://{app_lower}.com")

        subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return f"No desktop app found for {app_name}. Opened {url} in browser instead."

    try:
        from app_indexer import lookup_app
        matches = lookup_app(app_lower)
        if not matches:
            return (
                f"[error] Could not find or launch '{app_name}'. "
                f"Searched PC app index and PATH. Make sure it's installed."
            )

        best = matches[0]
        exec_line = best.get("exec_line", "")
        binary = best.get("exec", "")
        path = best.get("path", "")
        flatpak_id = best.get("flatpak_id", "")
        app_display_name = best.get("name", app_name)

        if _is_already_running(app_lower):
            return f"{app_name} is already running as {app_display_name}"

        launch_methods = []

        desktop_name = app_display_name
        if desktop_name.endswith(".desktop"):
            desktop_name = desktop_name[:-8]
        launch_methods.append(("gtk-launch", ["gtk-launch", desktop_name]))

        if flatpak_id:
            launch_methods.append(("flatpak", ["flatpak", "run", flatpak_id]))
            if binary and os.path.isfile(binary):
                launch_methods.append(("binary", [binary]))
            if exec_line:
                launch_methods.append(("exec_line", exec_line.split()))

        if binary and os.path.isfile(binary):
            launch_methods.append(("binary", [binary]))
        if exec_line:
            launch_methods.append(("exec_line", exec_line.split()))
        if path and os.path.isfile(path):
            launch_methods.append(("path", [path]))

        for method, cmd in launch_methods:
            try:
                subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                if _verify_process_running(app_lower):
                    return f"Launched {app_name} as {app_display_name}"
            except Exception:
                pass
    except Exception:
        pass

    return (
        f"[error] Could not find or launch '{app_name}'. "
        f"Searched PC app index and PATH. Make sure it's installed."
    )


def _is_already_running(keyword: str) -> bool:
    try:
        import psutil
        import os
        keyword_lower = keyword.lower()
        my_pid = os.getpid()
        my_ppid = os.getppid()
        SYSTEM_CMDLINE_PREFIXES = (
            "/usr/libexec/", "/usr/lib/", "/lib/",
            "/bin/", "/sbin/", "/usr/sbin/",
        )
        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                pid = proc.info.get("pid")
                if pid == my_pid or pid == my_ppid:
                    continue
                pname = (proc.info.get("name") or "").lower()
                cmdline = " ".join(proc.info.get("cmdline") or []).lower()
                if pname == keyword_lower or cmdline == keyword_lower:
                    if cmdline.startswith(SYSTEM_CMDLINE_PREFIXES):
                        continue
                    return True
                if pname.startswith(keyword_lower + "-") or cmdline.startswith(keyword_lower + "/"):
                    if cmdline.startswith(SYSTEM_CMDLINE_PREFIXES):
                        continue
                    return True
                if pname.startswith(keyword_lower + ".") or cmdline.startswith(keyword_lower + "."):
                    if cmdline.startswith(SYSTEM_CMDLINE_PREFIXES):
                        continue
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return False
    except Exception:
        return False


def _find_file(name: str, search_dirs: list = None) -> str:
    home = os.path.expanduser("~")
    dirs = search_dirs or [
        home,
        os.path.join(home, "Desktop"),
        os.path.join(home, "Documents"),
        os.path.join(home, "Downloads"),
        os.path.join(home, "Pictures"),
        os.path.join(home, "Videos"),
        os.path.join(home, "Music"),
        "/tmp",
        os.path.join(home, ".config"),
        os.path.join(home, ".local", "share"),
        "/opt",
    ]
    query_words = [w.lower() for w in name.strip().split() if len(w) > 2]
    if not query_words:
        query_words = [name.lower()]

    EXCLUDED_PATHS = {
        os.path.join(home, ".config", "google-chrome"),
        os.path.join(home, ".var"),
        os.path.join(home, ".cache"),
        os.path.join(home, ".cargo"),
        os.path.join(home, ".rustup"),
        os.path.join(home, ".local", "share", "Trash"),
    }

    scored = []
    for base in dirs:
        if not os.path.isdir(base):
            continue
        if any(base.startswith(ex) for ex in EXCLUDED_PATHS):
            continue
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in {"node_modules", "__pycache__"}]
            for f in files:
                f_lower = f.lower()
                score = sum(1 for word in query_words if word in f_lower)
                if score > 0:
                    scored.append((score, os.path.join(root, f)))
            for d in dirs:
                d_lower = d.lower()
                score = sum(1 for word in query_words if word in d_lower)
                if score > 0:
                    scored.append((score, os.path.join(root, d)))
            if len(scored) > 50:
                break
        if len(scored) > 50:
            break

    scored.sort(key=lambda x: x[0], reverse=True)
    matches = [m for _, m in scored[:20]]

    if not matches:
        return f"No files matching '{name}' found in common directories."

    lines = [f"Found {len(matches)} matches for '{name}':"]
    for m in matches:
        lines.append(f"- {m}")
    return "\n".join(lines)


def _open_folder(path: str) -> str:
    path = os.path.expanduser(os.path.expandvars(path))
    if not os.path.exists(path):
        return f"[error] Path not found: {path}"
    if not os.path.isdir(path):
        return f"[error] Not a folder: {path}"
    subprocess.Popen(["xdg-open", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return f"Opened folder {path}"


def _open_file(path: str) -> str:
    path = os.path.expanduser(os.path.expandvars(path))
    if not os.path.exists(path):
        return f"[error] File not found: {path}"
    subprocess.Popen(["xdg-open", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return f"Opened {path}"


def _open_file_with_app(path: str, app_name: str) -> str:
    path = os.path.expanduser(os.path.expandvars(path))
    app_name = _normalize_app_name(app_name)
    if not os.path.exists(path):
        return f"[error] File not found: {path}"
    try:
        from app_indexer import lookup_app
        matches = lookup_app(app_name)
        if not matches:
            return f"[error] Could not find app '{app_name}'. Make sure it's installed."
        best = matches[0]
        exec_line = best.get("exec_line", "")
        binary = best.get("exec", "")
        flatpak_id = best.get("flatpak_id", "")
        app_display_name = best.get("name", app_name)
        launch_methods = []
        if flatpak_id:
            launch_methods.append(("flatpak", ["flatpak", "run", flatpak_id, path]))
        if binary and os.path.isfile(binary):
            launch_methods.append(("binary", [binary, path]))
        if exec_line:
            launch_methods.append(("exec_line", exec_line.split() + [path]))
        for method, cmd in launch_methods:
            try:
                subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
                return f"Opened {path} in {app_display_name}"
            except Exception:
                pass
        return f"[error] Could not launch {app_name} with {path}"
    except Exception as e:
        return f"[error] Failed to open file with app: {e}"


def _copy_file(source: str, destination: str) -> str:
    source = os.path.expanduser(os.path.expandvars(source))
    destination = os.path.expanduser(os.path.expandvars(destination))
    if not os.path.exists(source):
        return f"[error] Source not found: {source}"
    try:
        if os.path.isdir(destination):
            dest_path = os.path.join(destination, os.path.basename(source))
        else:
            dest_path = destination
        shutil.copy2(source, dest_path)
        return f"Copied {source} -> {dest_path}"
    except Exception as e:
        return f"[error] Copy failed: {e}"


def _rename_file(source: str, destination: str) -> str:
    source = os.path.expanduser(os.path.expandvars(source))
    destination = os.path.expanduser(os.path.expandvars(destination))
    if not os.path.exists(source):
        return f"[error] Source not found: {source}"
    if os.path.exists(destination):
        return f"[error] Destination already exists: {destination}"
    os.rename(source, destination)
    return f"Renamed '{source}' -> '{destination}'"


def _open_url(url: str) -> str:
    WEBSITE_ALIASES = {
        "youtube": "https://www.youtube.com",
        "youtube.com": "https://www.youtube.com",
        "google": "https://www.google.com",
        "facebook": "https://www.facebook.com",
        "twitter": "https://twitter.com",
        "x.com": "https://x.com",
        "reddit": "https://www.reddit.com",
        "github": "https://github.com",
        "gmail": "https://mail.google.com",
        "amazon": "https://www.amazon.com",
        "netflix": "https://www.netflix.com",
        "twitch": "https://www.twitch.tv",
        "linkedin": "https://www.linkedin.com",
        "instagram": "https://www.instagram.com",
        "tiktok": "https://www.tiktok.com",
        "wikipedia": "https://www.wikipedia.org",
        "chatgpt": "https://chat.openai.com",
        "openai": "https://chat.openai.com",
        "bard": "https://bard.google.com",
        "gemini": "https://gemini.google.com",
        "bing": "https://www.bing.com",
        "yahoo": "https://www.yahoo.com",
        "duckduckgo": "https://duckduckgo.com",
        "ebay": "https://www.ebay.com",
        "spotify": "https://open.spotify.com",
        "soundcloud": "https://soundcloud.com",
        "discord": "https://discord.com",
        "whatsapp": "https://web.whatsapp.com",
        "telegram": "https://web.telegram.org",
        "messenger": "https://www.messenger.com",
        "pinterest": "https://www.pinterest.com",
        "snapchat": "https://www.snapchat.com",
        "zoom": "https://zoom.us",
        "notion": "https://www.notion.so",
        "trello": "https://trello.com",
        "figma": "https://www.figma.com",
        "canva": "https://www.canva.com",
        "medium": "https://medium.com",
        "quora": "https://www.quora.com",
        "stackoverflow": "https://stackoverflow.com",
        "hacker news": "https://news.ycombinator.com",
        "product hunt": "https://www.producthunt.com",
        "arxiv": "https://arxiv.org",
        "scholar": "https://scholar.google.com",
        "maps": "https://maps.google.com",
        "translate": "https://translate.google.com",
    }

    url_lower = url.lower().strip()
    if not url_lower.startswith(("http://", "https://")):
        if url_lower in WEBSITE_ALIASES:
            url = WEBSITE_ALIASES[url_lower]
        else:
            url = f"https://{url}"
    else:
        if url_lower in WEBSITE_ALIASES:
            url = WEBSITE_ALIASES[url_lower]

    subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return f"Opened {url} in browser"


def local_fallback(text: str) -> str:
    """Simple keyword-based command matcher for when the LLM API is unavailable."""
    t = text.lower().strip()

    if t.startswith("open ") or t.startswith("launch "):
        target = t.split(" ", 1)[1].strip()
        target = _normalize_app_name(target)
        if target in {
            "youtube", "youtube.com", "google", "facebook", "twitter", "x.com",
            "reddit", "github", "gmail", "amazon", "netflix", "twitch",
            "linkedin", "instagram", "tiktok", "wikipedia", "chatgpt", "openai",
            "bard", "gemini", "bing", "yahoo", "duckduckgo", "ebay", "spotify",
            "soundcloud", "discord", "whatsapp", "telegram", "messenger",
            "pinterest", "snapchat", "zoom", "notion", "trello", "figma",
            "canva", "medium", "quora", "stackoverflow", "hacker news",
            "product hunt", "arxiv", "scholar", "maps", "translate",
        }:
            return _open_url(target)
        result = _open_app(target)
        if not result.startswith("[error]"):
            return result
        find_result = _find_file(target)
        if not find_result.startswith("No files matching"):
            first_line = find_result.split("\n")[1] if "\n" in find_result else find_result
            path = first_line.lstrip("- ").strip()
            if path:
                if os.path.isdir(path):
                    return _open_folder(path)
                return _open_file(path)
        return result

    if t.startswith("search ") or t.startswith("google "):
        query = t.split(" ", 1)[1].strip()
        return _open_url(f"https://www.google.com/search?q={query.replace(' ', '+')}")

    if t.startswith("youtube "):
        query = t.split(" ", 1)[1].strip()
        return _open_url(f"https://www.youtube.com/results?search_query={query.replace(' ', '+')}")

    if t.startswith("find ") or t.startswith("search file "):
        name = t.split(" ", 1)[1].strip()
        return _find_file(name)

    if t.startswith("open file "):
        path = t.split(" ", 2)[2].strip()
        return _open_file(path)

    if t.startswith("open folder ") or t.startswith("open directory "):
        path = t.split(" ", 2)[2].strip()
        return _open_folder(path)

    if t.startswith("rename "):
        parts = t.split(" ", 1)[1].strip().split(" to ", 1)
        if len(parts) == 2:
            return _rename_file(parts[0].strip(), parts[1].strip())
        return "[error] Use: rename <old name> to <new name>"

    return None


def _move_file(source: str, destination: str) -> str:
    source = os.path.expanduser(os.path.expandvars(source))
    destination = os.path.expanduser(os.path.expandvars(destination))
    shutil.move(source, destination)
    return f"Moved {source} -> {destination}"


TOOLS = {
    "open_app": {
        "tier": TIER_SAFE,
        "function": _open_app,
        "declaration": {
            "name": "open_app",
            "description": "Opens any application on the PC by searching for it by name. Searches desktop entries, PATH, /usr/bin, /usr/local/bin, ~/.local/bin, /opt, Snap, Flatpak, and other common locations. Use this for apps like blender, firefox, vscode, discord, spotify, etc. If the user mentions an app name, use this tool.",
            "parameters": {
                "type": "object",
                "properties": {
                    "app_name": {
                        "type": "string",
                        "description": "Application name or partial name, e.g. 'blender', 'firefox', 'code', 'discord'",
                    }
                },
                "required": ["app_name"],
            },
        },
    },
    "open_url": {
        "tier": TIER_SAFE,
        "function": _open_url,
        "declaration": {
            "name": "open_url",
            "description": "Opens a URL in the default web browser. Use this for websites like YouTube, Google, etc.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "URL to open, e.g. 'https://www.youtube.com' or 'youtube.com'",
                    }
                },
                "required": ["url"],
            },
        },
    },
    "find_file": {
        "tier": TIER_SAFE,
        "function": _find_file,
        "declaration": {
            "name": "find_file",
            "description": "Searches the filesystem for files or folders matching a name. Searches Desktop, Documents, Downloads, Pictures, Videos, Music, home directory, and /tmp. Returns a list of matching paths.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "File or folder name to search for, e.g. 'essay', 'budget.xlsx', 'blender'",
                    }
                },
                "required": ["name"],
            },
        },
    },
    "open_file": {
        "tier": TIER_SAFE,
        "function": _open_file,
        "declaration": {
            "name": "open_file",
            "description": "Opens a file with the default application.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Full path to the file to open",
                    }
                },
                "required": ["path"],
            },
        },
    },
    "open_file_with_app": {
        "tier": TIER_SAFE,
        "function": _open_file_with_app,
        "declaration": {
            "name": "open_file_with_app",
            "description": "Opens a specific file with a specific application. Use this when the user asks to open a file in a particular app like LibreOffice, VLC, VS Code, etc.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Full path to the file to open",
                    },
                    "app_name": {
                        "type": "string",
                        "description": "Application name, e.g. 'libreoffice', 'vlc', 'vscode'",
                    }
                },
                "required": ["path", "app_name"],
            },
        },
    },
    "copy_file": {
        "tier": TIER_SENSITIVE,
        "function": _copy_file,
        "declaration": {
            "name": "copy_file",
            "description": "Copies a file from one location to another.",
            "parameters": {
                "type": "object",
                "properties": {
                    "source": {"type": "string", "description": "Source file path"},
                    "destination": {"type": "string", "description": "Destination folder or full path"},
                },
                "required": ["source", "destination"],
            },
        },
    },
    "open_folder": {
        "tier": TIER_SAFE,
        "function": _open_folder,
        "declaration": {
            "name": "open_folder",
            "description": "Opens a folder in the file manager. Use this to open directories like Downloads, Documents, etc.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Full path to the folder to open",
                    }
                },
                "required": ["path"],
            },
        },
    },
    "rename_file": {
        "tier": TIER_SENSITIVE,
        "function": _rename_file,
        "declaration": {
            "name": "rename_file",
            "description": "Renames a file or folder from one name to another.",
            "parameters": {
                "type": "object",
                "properties": {
                    "source": {"type": "string", "description": "Current full path"},
                    "destination": {"type": "string", "description": "New full path or new name"},
                },
                "required": ["source", "destination"],
            },
        },
    },
    "move_file": {
        "tier": TIER_SENSITIVE,
        "function": _move_file,
        "declaration": {
            "name": "move_file",
            "description": "Moves a file from one path to another.",
            "parameters": {
                "type": "object",
                "properties": {
                    "source": {"type": "string", "description": "Full source path"},
                    "destination": {"type": "string", "description": "Full destination path"},
                },
                "required": ["source", "destination"],
            },
        },
    },
    "read_file": {
        "tier": TIER_SAFE,
        "function": read_file,
        "declaration": {
            "name": "read_file",
            "description": "Reads the contents of a file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Full file path"}
                },
                "required": ["path"],
            },
        },
    },
    "write_file": {
        "tier": TIER_SENSITIVE,
        "function": write_file,
        "declaration": {
            "name": "write_file",
            "description": "Writes content to a file, overwriting existing content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Full file path"},
                    "content": {"type": "string", "description": "Content to write"},
                },
                "required": ["path", "content"],
            },
        },
    },
    "append_file": {
        "tier": TIER_SENSITIVE,
        "function": append_file,
        "declaration": {
            "name": "append_file",
            "description": "Appends content to the end of a file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Full file path"},
                    "content": {"type": "string", "description": "Content to append"},
                },
                "required": ["path", "content"],
            },
        },
    },
    "edit_file_line": {
        "tier": TIER_SENSITIVE,
        "function": edit_file_line,
        "declaration": {
            "name": "edit_file_line",
            "description": "Replaces a specific line in a file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Full file path"},
                    "line_number": {"type": "integer", "description": "Line number to replace (1-indexed)"},
                    "new_text": {"type": "string", "description": "New line content"},
                },
                "required": ["path", "line_number", "new_text"],
            },
        },
    },
    "shutdown_pc": {
        "tier": TIER_HIGH_RISK,
        "function": shutdown_pc,
        "declaration": {
            "name": "shutdown_pc",
            "description": "Schedules a PC shutdown.",
            "parameters": {
                "type": "object",
                "properties": {
                    "delay_minutes": {"type": "integer", "description": "Delay before shutdown (0 = immediate)"}
                },
                "required": [],
            },
        },
    },
    "restart_pc": {
        "tier": TIER_HIGH_RISK,
        "function": restart_pc,
        "declaration": {
            "name": "restart_pc",
            "description": "Schedules a PC restart.",
            "parameters": {
                "type": "object",
                "properties": {
                    "delay_minutes": {"type": "integer", "description": "Delay before restart (0 = immediate)"}
                },
                "required": [],
            },
        },
    },
    "cancel_shutdown": {
        "tier": TIER_SENSITIVE,
        "function": cancel_shutdown,
        "declaration": {
            "name": "cancel_shutdown",
            "description": "Cancels a scheduled shutdown or restart.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    "get_cpu_usage": {
        "tier": TIER_SAFE,
        "function": get_cpu_usage,
        "declaration": {
            "name": "get_cpu_usage",
            "description": "Gets current CPU usage percentage.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    "get_memory_usage": {
        "tier": TIER_SAFE,
        "function": get_memory_usage,
        "declaration": {
            "name": "get_memory_usage",
            "description": "Gets current memory usage.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    "get_disk_usage": {
        "tier": TIER_SAFE,
        "function": get_disk_usage,
        "declaration": {
            "name": "get_disk_usage",
            "description": "Gets disk usage for a path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to check (default /)"}
                },
                "required": [],
            },
        },
    },
    "get_battery_status": {
        "tier": TIER_SAFE,
        "function": get_battery_status,
        "declaration": {
            "name": "get_battery_status",
            "description": "Gets battery status if available.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    "get_full_pc_state": {
        "tier": TIER_SAFE,
        "function": get_full_pc_state,
        "declaration": {
            "name": "get_full_pc_state",
            "description": "Gets a summary of CPU, memory, disk, and battery.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    "set_brightness": {
        "tier": TIER_SENSITIVE,
        "function": set_brightness,
        "declaration": {
            "name": "set_brightness",
            "description": "Sets screen brightness (0-100).",
            "parameters": {
                "type": "object",
                "properties": {
                    "level": {"type": "integer", "description": "Brightness level 0-100"}
                },
                "required": ["level"],
            },
        },
    },
    "set_volume": {
        "tier": TIER_SENSITIVE,
        "function": set_volume,
        "declaration": {
            "name": "set_volume",
            "description": "Sets system volume (0-100).",
            "parameters": {
                "type": "object",
                "properties": {
                    "level": {"type": "integer", "description": "Volume level 0-100"}
                },
                "required": ["level"],
            },
        },
    },
    "get_brightness": {
        "tier": TIER_SAFE,
        "function": get_brightness,
        "declaration": {
            "name": "get_brightness",
            "description": "Gets current screen brightness.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    "get_volume": {
        "tier": TIER_SAFE,
        "function": get_volume,
        "declaration": {
            "name": "get_volume",
            "description": "Gets current system volume.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    "play_media": {
        "tier": TIER_SAFE,
        "function": play_media,
        "declaration": {
            "name": "play_media",
            "description": "Plays a media file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to media file"}
                },
                "required": ["path"],
            },
        },
    },
    "download_file": {
        "tier": TIER_SENSITIVE,
        "function": download_file,
        "declaration": {
            "name": "download_file",
            "description": "Downloads a file from a URL.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to download from"},
                    "destination": {"type": "string", "description": "Local destination path (optional)"},
                },
                "required": ["url"],
            },
        },
    },
    "research_topic": {
        "tier": TIER_SAFE,
        "function": research_topic,
        "declaration": {
            "name": "research_topic",
            "description": "Performs open-ended internet research on a topic and generates a report. Use this for research tasks. The report is saved to a file. If the user specifies a folder like Downloads, Documents, etc., pass that as save_path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "Topic to research"},
                    "max_results": {"type": "integer", "description": "Max search results (default 5)"},
                    "save_path": {"type": "string", "description": "Optional folder or full file path to save the report. If a folder is given, the file is saved inside it with an auto-generated name."},
                },
                "required": ["topic"],
            },
        },
    },
    "research_topic_browser": {
        "tier": TIER_SAFE,
        "function": research_topic_browser,
        "declaration": {
            "name": "research_topic_browser",
            "description": "Performs research using a real browser. Opens Google search, visits each result one at a time, scrapes full page content, and compiles a cited Markdown report. Use this when background search is blocked or the user wants thorough research with visible browser activity.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "Topic to research"},
                    "max_results": {"type": "integer", "description": "Max pages to scrape (default 5)"},
                    "save_path": {"type": "string", "description": "Optional folder or full file path to save the report."},
                    "headless": {"type": "boolean", "description": "Run browser invisibly (default true). Set false to watch the browser."},
                },
                "required": ["topic"],
            },
        },
    },
    "draft_email": {
        "tier": TIER_SENSITIVE,
        "function": draft_email,
        "declaration": {
            "name": "draft_email",
            "description": "Creates a draft email for manual review (does not send).",
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "Recipient email"},
                    "subject": {"type": "string", "description": "Email subject"},
                    "body": {"type": "string", "description": "Email body"},
                },
                "required": ["to", "subject", "body"],
            },
        },
    },
    "list_drafts": {
        "tier": TIER_SAFE,
        "function": list_drafts,
        "declaration": {
            "name": "list_drafts",
            "description": "Lists saved email drafts.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    "capture_webcam": {
        "tier": TIER_SENSITIVE,
        "function": capture_webcam,
        "declaration": {
            "name": "capture_webcam",
            "description": "Takes a webcam photo (on-demand only).",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string", "description": "Output filename (optional)"}
                },
                "required": [],
            },
        },
    },
    "list_captures": {
        "tier": TIER_SAFE,
        "function": list_captures,
        "declaration": {
            "name": "list_captures",
            "description": "Lists saved webcam captures.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    "add_folder_watch": {
        "tier": TIER_SENSITIVE,
        "function": add_folder_watch,
        "declaration": {
            "name": "add_folder_watch",
            "description": "Starts watching a folder for changes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "folder": {"type": "string", "description": "Folder path to watch"},
                    "action": {"type": "string", "description": "Action to take"},
                    "trigger": {"type": "string", "description": "Trigger type (created/modified)"},
                },
                "required": ["folder", "action"],
            },
        },
    },
    "remove_folder_watch": {
        "tier": TIER_SENSITIVE,
        "function": remove_folder_watch,
        "declaration": {
            "name": "remove_folder_watch",
            "description": "Stops watching a folder.",
            "parameters": {
                "type": "object",
                "properties": {
                    "folder": {"type": "string", "description": "Folder path to stop watching"}
                },
                "required": ["folder"],
            },
        },
    },
    "list_folder_watches": {
        "tier": TIER_SAFE,
        "function": list_folder_watches,
        "declaration": {
            "name": "list_folder_watches",
            "description": "Lists active folder watches.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    "gimp_batch_operation": {
        "tier": TIER_SENSITIVE,
        "function": gimp_batch_operation,
        "declaration": {
            "name": "gimp_batch_operation",
            "description": "Runs a GIMP batch operation on an image using actual GIMP Script-Fu. For poster/flyer/banner design, use operation='create_poster' which launches GIMP to generate a poster with text, colors, and optional downloaded images. Other operations: resize, autolevel, grayscale, blur, sharpen, brightness_contrast, flip, rotate, convert_format.",
            "parameters": {
                "type": "object",
                "properties": {
                    "operation": {"type": "string", "description": "Operation name: resize, autolevel, grayscale, blur, sharpen, brightness_contrast, flip, rotate, convert_format, create_poster"},
                    "input_path": {"type": "string", "description": "Path to the input image file (required for most operations, not needed for create_poster)"},
                    "output_path": {"type": "string", "description": "Path to save the output image (optional, auto-generated if omitted)"},
                    "width": {"type": "integer", "description": "Width in pixels (for resize or create_poster)"},
                    "height": {"type": "integer", "description": "Height in pixels (for resize or create_poster)"},
                    "radius": {"type": "number", "description": "Blur radius (for blur)"},
                    "amount": {"type": "number", "description": "Sharpen amount (for sharpen)"},
                    "brightness": {"type": "number", "description": "Brightness adjustment (for brightness_contrast)"},
                    "contrast": {"type": "number", "description": "Contrast adjustment (for brightness_contrast)"},
                    "direction": {"type": "string", "description": "Flip direction: horizontal or vertical (for flip)"},
                    "degrees": {"type": "integer", "description": "Rotation degrees (for rotate). Only 90, 180, or 270 are supported."},
                    "title": {"type": "string", "description": "Poster title text (for create_poster)"},
                    "subtitle": {"type": "string", "description": "Poster subtitle text (for create_poster)"},
                    "background_color": {"type": "string", "description": "Background hex color (for create_poster, default #1a1a2e)"},
                    "title_color": {"type": "string", "description": "Title text hex color (for create_poster, default #ffffff)"},
                    "subtitle_color": {"type": "string", "description": "Subtitle text hex color (for create_poster, default #e94560)"},
                    "font_size": {"type": "integer", "description": "Title font size in pixels (for create_poster, default 80)"},
                    "subtitle_font_size": {"type": "integer", "description": "Subtitle font size in pixels (for create_poster, default 40)"},
                    "asset_urls": {"type": "array", "items": {"type": "string"}, "description": "List of image URLs to download and add to the poster as layers (for create_poster)"},
                },
                "required": ["operation"],
            },
        },
    },
    "create_skill_from_research": {
        "tier": TIER_SENSITIVE,
        "function": create_skill_from_research,
        "declaration": {
            "name": "create_skill_from_research",
            "description": "Researches a topic and generates a new SKILL.md file for the agent skill system. Use this when the user asks to create a skill about a new domain.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "The topic to research and create a skill for"},
                    "skill_name": {"type": "string", "description": "Optional skill name slug (lowercase, hyphens only). Auto-derived from topic if omitted."},
                },
                "required": ["topic"],
            },
        },
    },
    "design_with_gimp": {
        "tier": TIER_SENSITIVE,
        "function": design_with_gimp,
        "declaration": {
            "name": "design_with_gimp",
            "description": "Designs an image or poster using GIMP from natural language. Handles asset downloading, composition planning, and GIMP batch operations. Use this for design requests like 'design a poster', 'create a flyer', 'make a banner'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "request": {"type": "string", "description": "Natural language design request, e.g. 'design a coffee-themed poster for a morning radio show'"},
                    "output_path": {"type": "string", "description": "Path to save the output image (optional, auto-generated if omitted)"},
                },
                "required": ["request"],
            },
        },
    },
}


def get_declarations():
    return [tool["declaration"] for tool in TOOLS.values()]


def dispatch(tool_name: str, args: dict) -> str:
    settings = get_settings()
    autonomy = settings.get("autonomy_mode", False)
    confirm_gate = settings.get("confirm_gate", True)

    if tool_name not in TOOLS:
        msg = f"[error] Unknown tool: {tool_name}"
        log_action(tool_name, args, "error", msg)
        return msg

    tool = TOOLS[tool_name]

    if tool["tier"] == TIER_HIGH_RISK:
        from consent import request_consent
        approved = request_consent("high_risk", tool_name=tool_name, args=args)
        if not approved:
            denied = f"[denied] {tool_name} requires explicit confirmation"
            log_action(tool_name, args, "denied", denied)
            return denied

    if tool["tier"] == TIER_SENSITIVE and confirm_gate and not autonomy:
        approved = confirm_action(tool_name, args)
        if not approved:
            denied = f"[denied] {tool_name} was not run"
            log_action(tool_name, args, "denied", denied)
            return denied

    try:
        result = tool["function"](**args)
        log_action(tool_name, args, "approved", result)
        return result
    except Exception as e:
        error_msg = f"[error] {tool_name} failed: {e}"
        log_action(tool_name, args, "error", error_msg)
        return error_msg
