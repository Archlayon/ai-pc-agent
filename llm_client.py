"""
Multi-backend LLM client for the AI PC Agent.

Priority:
1. Ollama local LLM (if available) - no rate limits, offline
2. Local fast-path for simple commands - instant execution
3. Local keyword fallback - always available

Supports multi-turn conversation memory stored in SQLite and tool calling.
Gemini API was removed due to rate limits and quota exhaustion.
"""
import os
import re
import threading

from memory import append_message, get_context, prune_old
from tool_registry import dispatch, get_declarations

# ECC-inspired enhancements — all imports are optional and fall back
# gracefully so existing behavior is preserved if any module is unavailable.
try:
    from status import set_context as _status_set_context, add_cost, set_autonomy
except Exception:
    _status_set_context = None

try:
    from skills_manager import get_system_prompt as _get_skill_prompt
except Exception:
    _get_skill_prompt = None

try:
    from context_compactor import (
        build_enhanced_context as _build_enhanced_context,
        update_preferences as _update_preferences,
    )
except Exception:
    _build_enhanced_context = None
    _update_preferences = None

SYSTEM_INSTRUCTION = (
    "You are a helpful AI assistant for a desktop PC. "
    "You have access to tools that can control the computer. "
    "IMPORTANT RULES: "
    "1. ONLY use tools that directly match what the user asked for. "
    "2. If the user asks to open a website like YouTube, Google, Facebook, etc., use open_url with the exact website URL. "
    "3. If the user asks to open an application like firefox, blender, vscode, discord, spotify, etc., use open_app with the exact app name. "
    "4. If you don't know if an app is installed, use find_file to search the filesystem for it first. "
    "5. If the user asks to find a file, use find_file with the filename. "
    "6. If the user asks to open a file with the default app, use open_file with the full path. "
    "7. If the user mentions a SPECIFIC app to open a file with (e.g. 'open in LibreOffice', 'play with VLC', 'open in VS Code'), ALWAYS use open_file_with_app with the path and app_name. "
    "8. If the user asks to rename a file, use rename_file with source and destination. "
    "9. If the user asks to move a file, use move_file with source and destination. "
    "10. If the user asks to copy a file, use copy_file with source and destination. "
    "11. If the user asks to research a topic, study something, or find information about a subject, ALWAYS use research_topic with the topic. If they specify where to save (e.g. 'save in Downloads', 'save in Documents'), pass that folder as save_path. "
    "12. NEVER call open_file or xdg-open when the user explicitly named an app. Always use open_file_with_app instead. "
    "13. NEVER call tools for things the user did not ask for. "
    "14. After executing, give a brief confirmation of what you actually did. "
    "15. Be concise and direct. Do not make up commands."
)

MODEL = "gemini-flash-latest"
SESSION_ID = "default"
LLM_TIMEOUT = 60

_APP_CACHE = {}


def _generate_with_timeout(fn, *args, timeout=LLM_TIMEOUT, **kwargs):
    result = [None]
    error = [None]

    def _target():
        try:
            result[0] = fn(*args, **kwargs)
        except Exception as e:
            error[0] = e

    t = threading.Thread(target=_target, daemon=True)
    t.start()
    t.join(timeout=timeout)

    if t.is_alive():
        raise TimeoutError(f"LLM request timed out after {timeout}s")
    if error[0]:
        raise error[0]
    return result[0]


def _fast_path(text: str) -> str:
    """Instant local execution for simple commands. No LLM needed."""
    t = text.lower().strip()

    with_app_patterns = [
        ("open ", " with ", "_open_file_with_app"),
        ("play ", " with ", "_open_file_with_app"),
        ("open ", " in ", "_open_file_with_app"),
        ("launch ", " with ", "_open_file_with_app"),
        ("start ", " with ", "_open_file_with_app"),
        ("watch ", " with ", "_open_file_with_app"),
        ("listen ", " with ", "_open_file_with_app"),
        ("play ", " using ", "_open_file_with_app"),
        ("open ", " using ", "_open_file_with_app"),
        ("launch ", " using ", "_open_file_with_app"),
        ("start ", " using ", "_open_file_with_app"),
        ("watch ", " using ", "_open_file_with_app"),
        ("listen ", " using ", "_open_file_with_app"),
    ]
    for prefix, sep, func_name in with_app_patterns:
        if t.startswith(prefix):
            rest = t[len(prefix):].strip()
            if sep in rest:
                target, app = rest.split(sep, 1)
                target = target.strip()
                app = app.strip().strip(".").strip("!").strip("?")
                if target and app:
                    from tool_registry import _open_file_with_app, _find_file, _open_file
                    path = None
                    if os.path.exists(target):
                        path = target
                    else:
                        find_result = _find_file(target)
                        if not find_result.startswith("No files matching"):
                            lines = find_result.split("\n")
                            target_basename = os.path.basename(target)
                            for line in lines[1:]:
                                candidate = line.lstrip("- ").strip()
                                if candidate and os.path.isfile(candidate):
                                    if os.path.basename(candidate).lower() == target_basename.lower():
                                        path = candidate
                                        break
                            if not path:
                                for line in lines[1:]:
                                    candidate = line.lstrip("- ").strip()
                                    if candidate and os.path.isfile(candidate):
                                        path = candidate
                                        break
                        if not path:
                            path = target
                        result = _open_file_with_app(path, app)
                        if not result.startswith("[error]"):
                            return result
                        return result

    try:
        from tool_registry import local_fallback
        result = local_fallback(text)
        if result:
            return result
    except Exception:
        pass

    if t.startswith("design_with_gimp(") or t.startswith("design with gimp("):
        from tools.gimp_designer import design_with_gimp
        import os
        common = {
            "downloads": os.path.expanduser("~/Downloads"),
            "download": os.path.expanduser("~/Downloads"),
            "documents": os.path.expanduser("~/Documents"),
            "document": os.path.expanduser("~/Documents"),
            "desktop": os.path.expanduser("~/Desktop"),
            "pictures": os.path.expanduser("~/Pictures"),
        }
        match = re.search(r"design_with_gimp\(['\"](.+?)['\"]\)", text, re.IGNORECASE)
        if not match:
            match = re.search(r"design with gimp\(['\"](.+?)['\"]\)", text, re.IGNORECASE)
        request = match.group(1) if match else text
        save_path = os.path.expanduser("~/Downloads")
        for kw in ["save it to ", "save in ", "save to "]:
            if kw in text.lower():
                _, path = text.split(kw, 1)
                path = path.strip().strip(".").strip("!").strip("?").strip()
                lower_path = path.lower()
                if lower_path in common:
                    save_path = common[lower_path]
                else:
                    words = re.findall(r"[a-zA-Z]+", lower_path)
                    for word in words:
                        if word in common:
                            save_path = common[word]
                            break
                    else:
                        save_path = os.path.expanduser(os.path.expandvars(path))
                break
        title = "poster"
        if "called" in request.lower():
            title = request.split("called", 1)[1].strip().split(" ")[0]
        elif "for a " in request.lower() or "for an " in request.lower():
            lowered = request.lower()
            for prefix in ["for a ", "for an "]:
                idx = lowered.find(prefix)
                if idx != -1:
                    rest = request[idx + len(prefix):].strip()
                    words = rest.split()
                    if words:
                        title = words[0]
                    break
        safe_title = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_") or "poster"
        output_path = os.path.join(save_path, f"{safe_title}_poster.png")
        return design_with_gimp(request, output_path=output_path)

    if any(t.startswith(kw) for kw in ["design a poster", "create a poster", "make a poster", "make a flyer", "make a banner"]):
        from tools.gimp_designer import design_with_gimp
        import os
        common = {
            "downloads": os.path.expanduser("~/Downloads"),
            "download": os.path.expanduser("~/Downloads"),
            "documents": os.path.expanduser("~/Documents"),
            "document": os.path.expanduser("~/Documents"),
            "desktop": os.path.expanduser("~/Desktop"),
            "pictures": os.path.expanduser("~/Pictures"),
        }
        save_path = os.path.expanduser("~/Downloads")
        for kw in ["save it to ", "save in ", "save to "]:
            if kw in text.lower():
                _, path = text.split(kw, 1)
                path = path.strip().strip(".").strip("!").strip("?").strip()
                lower_path = path.lower()
                if lower_path in common:
                    save_path = common[lower_path]
                else:
                    words = re.findall(r"[a-zA-Z]+", lower_path)
                    for word in words:
                        if word in common:
                            save_path = common[word]
                            break
                    else:
                        save_path = os.path.expanduser(os.path.expandvars(path))
                break
        title = "poster"
        subtitle = ""
        if "called" in text.lower():
            parts = text.split("called", 1)[1].strip()
            if "and save" in parts.lower():
                parts = parts.split("and save", 1)[0].strip()
            if "radio show" in parts.lower():
                title = parts.split("radio show", 1)[0].strip()
                subtitle = "Radio Show"
            else:
                title = parts.strip()
        elif "for a " in text.lower() or "for an " in text.lower():
            lowered = text.lower()
            for prefix in ["for a ", "for an "]:
                idx = lowered.find(prefix)
                if idx != -1:
                    rest = text[idx + len(prefix):].strip()
                    words = rest.split()
                    if words:
                        title = words[0]
                    break
        result = design_with_gimp(
            request=text,
            output_path=os.path.join(save_path, f"{re.sub(r'[^a-z0-9]+', '_', title.lower()).strip('_') or 'poster'}_poster.png"),
        )
        return result

    if t.startswith("open ") or t.startswith("launch "):
        target = t.split(" ", 1)[1].strip()
        from tool_registry import _normalize_app_name
        normalized = _normalize_app_name(target)
        if not normalized:
            return "[error] Please specify what to open. Example: 'open firefox'"
        from tool_registry import _open_app
        result = _open_app(normalized)
        if not result.startswith("[error]"):
            return result
        from tool_registry import _find_file, _open_file, _open_folder
        find_result = _find_file(target)
        if not find_result.startswith("No files matching"):
            first_line = find_result.split("\n")[1] if "\n" in find_result else find_result
            path = first_line.lstrip("- ").strip()
            if path:
                if os.path.isdir(path):
                    return _open_folder(path)
                return _open_file(path)
        return result

    if t.startswith("research ") or t.startswith("study ") or t.startswith("investigate "):
        prefix = "research " if t.startswith("research ") else "study " if t.startswith("study ") else "investigate "
        rest = t[len(prefix):].strip()
        save_path = ""
        topic = rest
        save_keywords = [" then save in ", " and save in ", " save in ", " save to ", " save report to "]
        for kw in save_keywords:
            if kw in rest:
                topic, save_path = rest.split(kw, 1)
                topic = topic.strip()
                save_path = save_path.strip().strip(".").strip("!").strip("?").removesuffix(" as a text file").removesuffix(" as a document").removesuffix(" as a pdf").strip()
                break
        if topic:
            from tool_registry import research_topic
            return research_topic(topic, max_results=5, save_path=save_path)
        return "[error] Please specify a topic to research. Example: 'research how x-rays work'"

    if t.startswith("scrape "):
        url = t.split(" ", 1)[1].strip()
        from research_scraper import scrape_page
        from pathlib import Path
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            result = scrape_page(url, Path(tmpdir))
            if result:
                return f"Scraped {url}\nTitle: {result['title']}\n\n{result['markdown'][:2000]}"
            return f"[error] Could not scrape {url}"

    if t.startswith("search ") or t.startswith("google "):
        query = t.split(" ", 1)[1].strip()
        research_keywords = ["about ", "how ", "what ", "why ", "info ", "information ", "learn ", "study ", "explain ", "tell me "]
        if any(query.lower().startswith(kw) for kw in research_keywords) or len(query.split()) > 3:
            from tool_registry import research_topic
            return research_topic(query, max_results=5)
        from tool_registry import _open_url
        return _open_url(f"https://www.google.com/search?q={query.replace(' ', '+')}")

    if t.startswith("youtube "):
        query = t.split(" ", 1)[1].strip()
        from tool_registry import _open_url
        return _open_url(f"https://www.youtube.com/results?search_query={query.replace(' ', '+')}")

    if t.startswith("find ") or t.startswith("search file "):
        name = t.split(" ", 1)[1].strip()
        from tool_registry import _find_file
        return _find_file(name)

    if t.startswith("open file "):
        path = t.split(" ", 2)[2].strip()
        from tool_registry import _open_file
        return _open_file(path)

    if t.startswith("open folder ") or t.startswith("open directory "):
        path = t.split(" ", 2)[2].strip()
        from tool_registry import _open_folder
        return _open_folder(path)

    if t.startswith("rename "):
        parts = t.split(" ", 1)[1].strip().split(" to ", 1)
        if len(parts) == 2:
            from tool_registry import _rename_file
            return _rename_file(parts[0].strip(), parts[1].strip())
        return "[error] Use: rename <old name> to <new name>"

    if t.startswith("copy ") or t.startswith("duplicate "):
        parts = t.split(" ", 1)[1].strip().split(" to ", 1)
        if len(parts) == 2:
            from tool_registry import _copy_file
            return _copy_file(parts[0].strip(), parts[1].strip())
        return "[error] Use: copy <source> to <destination>"

    if t.startswith("move ") or t.startswith("mv "):
        parts = t.split(" ", 1)[1].strip().split(" to ", 1)
        if len(parts) == 2:
            from tool_registry import _move_file
            return _move_file(parts[0].strip(), parts[1].strip())
        return "[error] Use: move <source> to <destination>"

    FILE_KEYWORDS = {
        "find ", "search file ", "open file ", "open folder ", "open directory ",
    }
    if any(t.startswith(kw) for kw in FILE_KEYWORDS):
        from tool_registry import _find_file
        return _find_file(t)

    try:
        from app_indexer import lookup_app
        from tool_registry import _normalize_app_name, _open_app
        normalized = _normalize_app_name(t)
        if normalized:
            matches = lookup_app(normalized)
            SYSTEM_PATHS = {
                "/usr/libexec", "/usr/lib", "/lib", "/bin", "/sbin",
                "/usr/sbin", "/usr/local/lib", "/usr/local/libexec",
            }
            user_apps = [
                m for m in matches
                if not any(
                    m.get("path", "").startswith(p)
                    for p in SYSTEM_PATHS
                )
            ]
            if user_apps:
                result = _open_app(normalized)
                if not result.startswith("[error]"):
                    return result
    except Exception:
        pass

    return None


def _call_gemini(user_text: str, session_id: str) -> str:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set")

    client = genai.Client(api_key=api_key)

    # Use enhanced context (includes session summaries + preferences) if available,
    # otherwise fall back to the original get_context
    if _build_enhanced_context is not None:
        try:
            context = _build_enhanced_context(session_id, max_messages=20)
        except Exception:
            context = get_context(session_id)
            prune_old(session_id)
    else:
        context = get_context(session_id)
        prune_old(session_id)

    # Build skill-augmented system prompt: base rules + contextually-loaded skills
    system_instruction = SYSTEM_INSTRUCTION
    if _get_skill_prompt is not None:
        try:
            augmented_prompt, matched_skill_names = _get_skill_prompt(user_text, SYSTEM_INSTRUCTION)
            if augmented_prompt and augmented_prompt != SYSTEM_INSTRUCTION:
                system_instruction = augmented_prompt
        except Exception:
            pass  # fall back to SYSTEM_INSTRUCTION if skills_manager fails

    tool = types.Tool(
        function_declarations=[
            types.FunctionDeclaration(**decl) for decl in get_declarations()
        ]
    )

    contents = []
    for msg in context:
        role = "user" if msg["role"] == "user" else "model"
        contents.append(types.Content(role=role, parts=[types.Part(text=msg["content"])]))

    response = _generate_with_timeout(
        client,
        MODEL,
        contents,
        types.GenerateContentConfig(
            tools=[tool],
            system_instruction=system_instruction,
        ),
    )

    candidate = response.candidates[0]
    parts = candidate.content.parts or []

    if not parts:
        return ""

    output_parts = []
    for part in parts:
        if part.function_call:
            name = part.function_call.name
            args = dict(part.function_call.args)
            print(f"[gemini] wants to call: {name}({args})")
            result = dispatch(name, args)
            print(f"[result] {result}")
            append_message(session_id, "assistant", f"Called {name}: {result}")
            output_parts.append(result)
        elif part.text:
            print(f"[gemini] {part.text}")
            append_message(session_id, "assistant", part.text)
            output_parts.append(part.text)

    return "\n".join(output_parts) if output_parts else ""


def _call_ollama(user_text: str, session_id: str) -> str:
    from ollama_client import ask_agent as ollama_ask
    response = ollama_ask(user_text)
    append_message(session_id, "assistant", response)
    return response


def _local_fallback(text: str) -> str:
    try:
        from tool_registry import local_fallback
        return local_fallback(text)
    except Exception:
        return None


_GREETINGS = {
    "hello", "hi", "hey", "howdy", "sup", "what's up",
    "good morning", "good afternoon", "good evening",
    "yo", "how are you", "how's it going", "agent",
}


def _simple_response(text: str) -> str:
    try:
        from tool_registry import _normalize_app_name
        t = _normalize_app_name(text).strip()
    except Exception:
        t = text.lower().strip()
    if t in {"hello", "hi", "hey", "howdy", "sup", "yo"}:
        return "Hello! How can I help you?"
    if t in {"how are you", "how's it going", "how are you doing"}:
        return "I'm doing great, thanks for asking!"
    if t in {"who are you", "what are you", "your name"}:
        return "I'm your AI PC assistant. I can open apps, search files, and help you control your computer."
    if t in {"thank you", "thanks", "thx"}:
        return "You're welcome!"
    if t in {"bye", "goodbye", "see you"}:
        return "Goodbye! Say hey agent anytime you need me."
    if t == "agent":
        return "Yes, I'm here. What can I do for you?"
    return None


def ask_agent(user_text: str, session_id: str = SESSION_ID) -> str:
    append_message(session_id, "user", user_text)

    # Extract persistent preferences from the user message (ECC Memory Vault concept)
    if _update_preferences is not None:
        try:
            _update_preferences("user", user_text)
        except Exception:
            pass

    # Report context pressure to the status observability layer
    if _status_set_context is not None:
        try:
            from memory import get_context as _gc
            recent = _gc(session_id, limit=20)
            _status_set_context(len(recent), limit=20)
        except Exception:
            pass

    fast = _fast_path(user_text)
    if fast:
        append_message(session_id, "assistant", fast)
        return fast

    simple = _simple_response(user_text)
    if simple:
        append_message(session_id, "assistant", simple)
        return simple

    backends = []

    try:
        from ollama_client import is_available
        if is_available():
            backends.append(("ollama", lambda: _call_ollama(user_text, session_id)))
    except Exception:
        pass

    last_error = None
    for name, fn in backends:
        try:
            result = fn()
            if result:
                return result
        except Exception as e:
            last_error = e
            error_str = str(e)
            if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str or "quota" in error_str.lower():
                print(f"[llm] {name} rate limited, trying next backend...", flush=True)
            else:
                print(f"[llm] {name} error: {e}", flush=True)

    simple = _simple_response(user_text)
    if simple:
        append_message(session_id, "assistant", simple)
        return simple

    search_query = user_text.strip()
    if search_query:
        try:
            from tool_registry import _open_url
            return _open_url(f"https://www.google.com/search?q={search_query.replace(' ', '+')}")
        except Exception:
            pass

    msg = "[error] All LLM backends failed. Try installing Ollama for offline use."
    if last_error:
        msg += f" Last error: {last_error}"
    append_message(session_id, "assistant", msg)
    return msg


if __name__ == "__main__":
    print("Type a request (e.g. 'open firefox'), Ctrl+C to quit.")
    while True:
        try:
            text = input("> ")
        except KeyboardInterrupt:
            break
        if text:
            print(ask_agent(text))
