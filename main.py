"""
AI PC Agent — main entry point.

Usage:
    python3 main.py              # CLI mode (text input)
    python3 main.py --tray       # Background system tray daemon
    python3 main.py --voice      # CLI mode with voice input
    python3 main.py --widget     # Floating GUI widget
    python3 main.py --hud        # Jarvis arc reactor HUD
"""
import argparse
import sys

from settings import get_settings


def run_cli(voice: bool = False):
    if voice:
        from whisper_input import listen
        print("[agent] Voice mode — speak after the beep.")
        try:
            text = listen(model_size=get_settings().get("whisper_model", "small"))
        except Exception as e:
            print(f"[error] Voice input failed: {e}")
            return
        print(f"[agent] You said: {text}")
        if text:
            from llm_client import ask_agent
            ask_agent(text)
        return

    from llm_client import ask_agent
    print("Type a request (e.g. 'open firefox'), Ctrl+C to quit.")
    while True:
        try:
            text = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if text:
            ask_agent(text)


def run_tray():
    from tray import run_tray
    run_tray()


def run_widget():
    from main_widget import AgentWidget
    widget = AgentWidget()
    widget.run()


def run_hud():
    import importlib.util
    import os

    hud_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jarvis")
    if hud_dir not in sys.path:
        sys.path.insert(0, hud_dir)

    candidates = [
        os.path.join(hud_dir, "jarvis_main.py"),
        os.path.join(hud_dir, "__main__.py"),
    ]
    module_path = next((p for p in candidates if os.path.exists(p)), None)
    if module_path is None:
        raise ImportError(f"No jarvis_main module found in {hud_dir}")

    spec = importlib.util.spec_from_file_location("jarvis_main", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    entry = getattr(module, "main", None) or getattr(module, "jarvis_main", None)
    if entry is None:
        raise AttributeError("jarvis_main module has no main() or jarvis_main() entry point")
    entry()


def run_audit():
    """Run the security self-audit and print results."""
    try:
        from security_audit import print_report
        print_report()
    except ImportError:
        print("[error] Security audit module not available.")


def run_status():
    """Print the current agent status payload."""
    try:
        from status import load_status
        import json
        status = load_status()
        if status:
            print(json.dumps(status, indent=2))
        else:
            print("[info] No status file found. The agent may not be running.")
    except ImportError:
        print("[error] Status module not available.")


def main():
    parser = argparse.ArgumentParser(description="AI PC Agent")
    parser.add_argument("--tray", action="store_true", help="Run as background system tray daemon")
    parser.add_argument("--voice", action="store_true", help="CLI mode with voice input")
    parser.add_argument("--widget", action="store_true", help="Floating GUI widget")
    parser.add_argument("--hud", action="store_true", help="Jarvis arc reactor HUD")
    parser.add_argument("--audit", action="store_true", help="Run security self-audit")
    parser.add_argument("--status", action="store_true", help="Print current agent status")
    args = parser.parse_args()

    if args.audit:
        run_audit()
    elif args.status:
        run_status()
    elif args.tray:
        run_tray()
    elif args.widget:
        run_widget()
    elif args.hud:
        run_hud()
    else:
        run_cli(voice=args.voice)


if __name__ == "__main__":
    main()
