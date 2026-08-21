#!/usr/bin/env bash
# Launch Jarvis HUD (arc reactor) with voice control
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/jarvis"
exec python3 jarvis_main.py
