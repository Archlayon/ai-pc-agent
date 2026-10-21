#!/usr/bin/env bash
# AI PC Agent launcher
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="${AI_PC_AGENT_HOME:-${HOME}/.local/share/ai-pc-agent}"

# Prefer the project venv, then the installed venv, then whatever python3 is on PATH.
PY=""
for candidate in "${REPO_DIR}/venv" "${INSTALL_DIR}/venv"; do
    if [[ -x "${candidate}/bin/python" ]]; then
        PY="${candidate}/bin/python"
        break
    fi
done
PY="${PY:-python3}"

cd "${REPO_DIR}"

MODE="${1:-cli}"
[[ $# -gt 0 ]] && shift || true

case "$MODE" in
    tray)
        exec "$PY" main.py --tray "$@"
        ;;
    voice)
        exec "$PY" main.py --voice "$@"
        ;;
    widget)
        exec "$PY" main.py --widget "$@"
        ;;
    hud|jarvis)
        exec "$PY" main.py --hud "$@"
        ;;
    hotkey)
        exec "$PY" hotkey_listener.py "$@"
        ;;
    cli)
        exec "$PY" main.py "$@"
        ;;
    audit)
        exec "$PY" main.py --audit "$@"
        ;;
    status)
        exec "$PY" main.py --status "$@"
        ;;
    -h|--help|help)
        echo "Usage: $0 [mode]"
        echo ""
        echo "Modes:"
        echo "  hud       Jarvis arc reactor HUD with voice control (main mode)"
        echo "  tray      Background system tray daemon"
        echo "  widget    Floating GUI widget"
        echo "  voice     CLI mode with voice input"
        echo "  cli       CLI text mode (default)"
        echo "  hotkey    Global hotkey listener only"
        echo "  audit     Run the security self-audit"
        echo "  status    Print the current agent status"
        echo ""
        echo "Examples:"
        echo "  $0 hud"
        echo "  $0 tray"
        echo "  $0 voice"
        ;;
    *)
        # Pass through flags like --tray / --voice / --hud straight to main.py
        exec "$PY" main.py "$MODE" "$@"
        ;;
esac
