"""
Context compaction and preference persistence for the AI PC Agent.

This layer sits ON TOP of the existing SQLite memory (memory.py) without
modifying it. It adds:

1. Session summarization: periodically distills old conversation messages
   into a compact summary, freeing context budget.
2. Preference extraction: captures persistent user facts (preferred apps,
   save locations, autonomy habits) into a separate JSON store.
3. Selective recall: when a new session starts, loads summaries and
   preferences from prior sessions instead of dumping the last N messages.

Maps to ECC's Memory Vault concept: portable, inspectable, scoped facts
that survive context resets.
"""
import json
import os
import re
from datetime import datetime, timezone

PREF_PATH = os.path.expanduser("~/.local/share/ai-pc-agent/preferences.json")
SUMMARY_DIR = os.path.expanduser("~/.local/share/ai-pc-agent/summaries")
MEMORY_DB_DIR = os.path.dirname(os.path.expanduser("~/.local/share/ai-pc-agent/memory.db"))

SUMMARY_THRESHOLD = 8  # messages before a summarization pass kicks in
MAX_SUMMARY_CHARS = 2000  # cap each session summary


def _ensure_dirs():
    os.makedirs(os.path.dirname(PREF_PATH), exist_ok=True)
    os.makedirs(SUMMARY_DIR, exist_ok=True)


_ensure_dirs()


def load_preferences() -> dict:
    """Load persistent user preferences."""
    try:
        with open(PREF_PATH, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_preferences(prefs: dict):
    """Persist preferences to disk."""
    _ensure_dirs()
    tmp = PREF_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(prefs, f, indent=2)
    os.replace(tmp, PREF_PATH)


def extract_preferences_from_message(role: str, content: str) -> dict:
    """Scan a user message for persistent preferences and return updates.

    Detects:
    - "I prefer X over Y" → {"preferred_app": "X"}
    - "save in ~/Documents" → {"default_save_path": "~/Documents"}
    - "use Ollama" → {"preferred_backend": "ollama"}

    Pure extraction — does not modify the SQLite memory.
    """
    prefs = {}
    content_lower = content.lower()

    # Preferred app detection: "I prefer Firefox over Chrome"
    m = re.search(r"prefer\s+(\S+)\s+over\s+(\S+)", content_lower)
    if m:
        prefs["preferred_app"] = m.group(1).rstrip(".")

    # Save path detection: "save in ~/Documents" or "save to Documents"
    m = re.search(r"save\s+(?:in|to)\s+(\S+)", content_lower)
    if m:
        prefs["default_save_path"] = m.group(1)

    # Backend preference: "use Ollama" / "use Gemini"
    for backend in ("ollama", "gemini", "openai"):
        if f"use {backend}" in content_lower:
            prefs["preferred_backend"] = backend

    return prefs


def update_preferences(role: str, content: str) -> dict:
    """Extract preferences from a message and merge them into the store."""
    new_prefs = extract_preferences_from_message(role, content)
    if not new_prefs:
        return {}
    existing = load_preferences()
    existing.update(new_prefs)
    save_preferences(existing)
    return new_prefs


def summarize_session(session_id: str, messages: list[dict]) -> str:
    """Create a compact summary of a session's messages.

    If an LLM backend is available, use it for summarization.
    Otherwise, fall back to extracting key entities and actions.
    """
    if not messages:
        return ""

    # Try LLM-based summarization first
    try:
        from llm_client import _generate_with_timeout, _call_ollama, _fast_path
        from ollama_client import is_available

        user_msgs = [m for m in messages if m.get("role") == "user"]
        assistant_msgs = [m for m in messages if m.get("role") == "assistant"]

        summary_prompt = _build_summary_prompt(session_id, user_msgs, assistant_msgs)
        if is_available():
            return _generate_with_timeout(_call_ollama, summary_prompt, timeout=30)
        else:
            return _fallback_summary(user_msgs, assistant_msgs)
    except Exception:
        return _fallback_summary(
            [m for m in messages if m.get("role") == "user"],
            [m for m in messages if m.get("role") == "assistant"],
        )


def _build_summary_prompt(session_id: str, user_msgs: list, assistant_msgs: list) -> str:
    """Build a prompt for LLM-based session summarization."""
    parts = [
        "Summarize this agent session concisely for future recall.",
        f"Session ID: {session_id}",
        f"User messages ({len(user_msgs)}):",
    ]
    for m in user_msgs[:10]:
        parts.append(f"  - {m.get('content', '')[:200]}")
    parts.append(f"\nAssistant/tool results ({len(assistant_msgs)}):")
    for m in assistant_msgs[:10]:
        parts.append(f"  - {m.get('content', '')[:200]}")
    parts.append("\nReturn a 3-5 sentence summary of what was accomplished,")
    parts.append("key decisions made, tools used, and any persistent facts.")
    return "\n".join(parts)


def _fallback_summary(user_msgs: list, assistant_msgs: list) -> str:
    """Keyword-based summary when no LLM is available."""
    summary_parts = ["Session summary:"]

    for m in user_msgs:
        content = m.get("content", "")[:100]
        summary_parts.append(f"  User: {content}")

    tool_calls = []
    for m in assistant_msgs:
        content = m.get("content", "")
        if "Called" in content:
            tool_calls.append(content[:100])

    if tool_calls:
        summary_parts.append(f"  Tools used ({len(tool_calls)}):")
        for tc in tool_calls[:3]:
            summary_parts.append(f"    {tc}")

    return "\n".join(summary_parts)[:MAX_SUMMARY_CHARS]


def save_session_summary(session_id: str, messages: list[dict]):
    """Write a session summary to disk for future recall.

    Returns the summary text.
    """
    summary = summarize_session(session_id, messages)
    if not summary:
        return ""

    _ensure_dirs()
    path = os.path.join(SUMMARY_DIR, f"{session_id}.md")
    entry = {
        "session_id": session_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
    }
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(entry, f, indent=2)
    os.replace(tmp, path)
    return summary


def load_session_summaries() -> list[dict]:
    """Load all session summaries, sorted by newest first."""
    summaries = []
    if not os.path.isdir(SUMMARY_DIR):
        return summaries
    for fname in sorted(os.listdir(SUMMARY_DIR), reverse=True):
        if not fname.endswith(".md"):
            continue
        try:
            with open(os.path.join(SUMMARY_DIR, fname), "r") as f:
                entry = json.load(f)
                summaries.append(entry)
        except (json.JSONDecodeError, OSError):
            continue
    return summaries


def build_enhanced_context(session_id: str, max_messages: int = 20) -> list[dict]:
    """Build conversation context by combining recent messages with
    prior session summaries and preferences.

    This wraps memory.get_context without modifying it — it adds
    summary + preference context BEFORE the recent messages.
    """
    from memory import get_context, append_message

    recent = get_context(session_id, limit=max_messages)

    # Load prior summaries (excluding current session)
    summaries = load_session_summaries()
    other_summaries = [s for s in summaries if s["session_id"] != session_id]

    context = []

    # Inject preference context as a system note
    prefs = load_preferences()
    if prefs:
        pref_msg = "## User Preferences (from prior sessions)\n"
        for k, v in prefs.items():
            pref_msg += f"- {k}: {v}\n"
        context.append({"role": "user", "content": pref_msg.strip()})

    # Inject prior session summaries as context
    if other_summaries:
        summary_parts = ["## Prior Session Context (summarized)\n"]
        for s in other_summaries[:3]:  # last 3 sessions
            summary_parts.append(f"[{s['session_id']}] {s['summary'][:200]}\n")
        context.append({"role": "user", "content": "\n".join(summary_parts).strip()})

    # Append recent messages
    context.extend(recent)

    return context


def should_summarize(session_id: str, message_count: int) -> bool:
    """Check if the session has enough messages to warrant summarization."""
    return message_count >= SUMMARY_THRESHOLD
