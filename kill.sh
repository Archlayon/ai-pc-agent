#!/usr/bin/env bash
# Kill all AI PC Agent / Jarvis processes
set -euo pipefail

echo "Stopping all Jarvis HUD instances..."
pkill -f "jarvis_ui.py" 2>/dev/null || true
pkill -f "QtWebEngineProcess.*jarvis" 2>/dev/null || true
pkill -f "python3 main.py" 2>/dev/null || true
sleep 1

remaining=$(ps aux | grep -E "jarvis_ui.py|QtWebEngineProcess.*jarvis|python3 main.py" | grep -v grep | wc -l || true)
if [ "$remaining" -gt 0 ]; then
    echo "Force killing remaining processes..."
    pkill -9 -f "jarvis_ui.py" 2>/dev/null || true
    pkill -9 -f "QtWebEngineProcess.*jarvis" 2>/dev/null || true
    pkill -9 -f "python3 main.py" 2>/dev/null || true
    sleep 1
fi

remaining=$(ps aux | grep -E "jarvis_ui.py|QtWebEngineProcess.*jarvis|python3 main.py" | grep -v grep | wc -l || true)
if [ "$remaining" -eq 0 ]; then
    echo "All Jarvis processes stopped."
else
    echo "Warning: $remaining processes still running"
    ps aux | grep -E "jarvis_ui.py|QtWebEngineProcess.*jarvis|python3 main.py" | grep -v grep
fi
