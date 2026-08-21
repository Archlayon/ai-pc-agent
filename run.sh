#!/usr/bin/env bash
# AI PC Agent launcher
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

MODE="${1:-cli}"
shift || true

case "$MODE" in
    tray)
        exec python3 main.py --tray "$@"
        ;;
    voice)
        exec python3 main.py --voice "$@"
        ;;
    widget)
        exec python3 main.py --widget "$@"
        ;;
    hud|jarvis)
        exec python3 main.py --hud "$@"
        ;;
    -h|--help|help)
        echo "Usage: $0 [mode]"
        echo ""
        echo "Modes:"
        echo "  tray      Background system tray daemon (recommended)"
        echo "  hud       Jarvis arc reactor HUD with voice control"
        echo "  widget    Floating GUI widget"
        echo "  voice     CLI mode with voice input"
        echo "  cli       CLI text mode (default)"
        echo ""
        echo "Examples:"
        echo "  $0 hud"
        echo "  $0 tray"
        echo "  $0 voice"
        ;;
    *)
        exec python3 main.py "$@"
        ;;
esac
