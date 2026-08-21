#!/usr/bin/env bash
set -euo pipefail

APP_NAME="AI PC Agent"
DESKTOP_FILE="com.layon.aiagent.desktop"
INSTALL_DIR="${HOME}/.local/share/ai-pc-agent"
CONFIG_DIR="${HOME}/.config/ai-pc-agent"
APPLICATIONS_DIR="${HOME}/.local/share/applications"
AUTOSTART_DIR="${HOME}/.config/autostart"

echo "=== ${APP_NAME} Uninstaller ==="
echo ""

read -p "This will remove ${APP_NAME} and all its data. Continue? [y/N] " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 0
fi

# Stop running processes
echo "[info] Stopping running processes..."
pkill -f "ai-pc-agent" || true
pkill -f "main.py --tray" || true
pkill -f "hotkey_listener.py" || true

# Remove desktop files
echo "[info] Removing desktop files..."
rm -f "${APPLICATIONS_DIR}/${DESKTOP_FILE}"
rm -f "${AUTOSTART_DIR}/${DESKTOP_FILE}"

# Remove installation directory
echo "[info] Removing installation directory..."
rm -rf "${INSTALL_DIR}"

# Remove config (optional)
read -p "Remove configuration and logs too? [y/N] " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    rm -rf "${CONFIG_DIR}"
    echo "[ok] Configuration removed"
fi

echo ""
echo "[ok] ${APP_NAME} has been uninstalled."
echo ""
