"""
Ollama local LLM client for the AI PC Agent.

Provides a drop-in replacement for the Gemini API using locally-hosted
models via Ollama. Supports function calling with the same tool registry.
"""
import os
import threading

import ollama
from ollama import ChatResponse

from tool_registry import dispatch, get_declarations

MODEL = os.environ.get("OLLAMA_MODEL", "llama3.1:8b")
HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
LLM_TIMEOUT = 20


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
        raise TimeoutError(f"Ollama request timed out after {timeout}s")
    if error[0]:
        raise error[0]
    return result[0]


def ask_agent(user_text: str) -> str:
    tools = get_declarations()
    messages = [
        {
            "role": "system",
            "content": (
                "You are a helpful AI assistant for a desktop PC. "
                "You have access to tools that can control the computer. "
                "IMPORTANT RULES: "
                "1. ONLY use tools that directly match what the user asked for. "
                "2. If the user asks to open a website like YouTube, Google, Facebook, etc., use open_url with the exact website URL. "
                "3. If the user asks to open an application like firefox, blender, vscode, discord, spotify, etc., use open_app with the exact app name. "
                "4. If you don't know if an app is installed, use find_file to search the filesystem for it first. "
                "5. If the user asks to find a file, use find_file with the filename. "
                "6. If the user asks to open a file, use open_file with the full path. "
                "7. If the user asks to rename a file, use rename_file with source and destination. "
                "8. NEVER call tools for things the user did not ask for. "
                "9. After executing, give a brief confirmation of what you actually did. "
                "10. Be concise and direct. Do not make up commands."
            ),
        },
        {"role": "user", "content": user_text},
    ]

    response: ChatResponse = _generate_with_timeout(
        ollama.chat,
        model=MODEL,
        messages=messages,
        tools=tools if tools else None,
        options={"num_ctx": 4096},
    )

    msg = response["message"]
    tool_calls = msg.get("tool_calls")

    if tool_calls:
        output_parts = []
        for tc in tool_calls:
            name = tc["function"]["name"]
            args = tc["function"]["arguments"]
            print(f"[ollama] wants to call: {name}({args})")
            result = dispatch(name, args)
            print(f"[result] {result}")
            output_parts.append(result)
        return "\n".join(output_parts) if output_parts else "[ollama] (no result)"

    content = msg.get("content", "").strip()
    return content if content else "[ollama] (no response)"


def is_available() -> bool:
    try:
        import urllib.request
        req = urllib.request.urlopen(HOST + "/api/tags", timeout=2)
        return req.status == 200
    except Exception:
        return False


def list_models():
    try:
        client = ollama.Client(host=HOST)
        resp = _generate_with_timeout(client.list, timeout=10)
        models = resp.get("models", [])
        return [m.get("name", "") for m in models]
    except Exception:
        return []
