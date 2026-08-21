# AI PC Agent

Voice-activated desktop AI automation agent. Runs as a native, non-intrusive system widget with a human-in-the-loop safety protocol.

## Features

- **Voice + Text Input:** Faster-Whisper (offline) speech-to-text and floating text widget
- **Global Hotkey:** Wayland-native Control+L activation via xdg-desktop-portal
- **LLM Tool-Calling:** Gemini-powered reasoning with function dispatch
- **Agent Hierarchy:** Main agent, workers, fixers with self-healing supervisor
- **Safety:** Tiered confirmations, audit logging, autonomy opt-in, rollback snapshots
- **Tools:** Open apps, move files, edit files, monitor PC state, webcam, email drafts, folder watch, media, downloads, shutdown/restart, internet research
- **Cross-platform:** Linux (Windows support planned)

## Quick Install

```bash
# Clone or extract the project
cd ai-pc-agent

# Run the installer
chmod +x install.sh
./install.sh
```

The installer will:
1. Install system dependencies (`python3-dbus`, `brightnessctl`, etc.)
2. Create a Python virtual environment
3. Install all Python dependencies
4. Install the desktop file for global hotkey support
5. Create launcher scripts

## Manual Setup

If you prefer manual setup:

```bash
# 1. System dependencies (Fedora)
sudo dnf install python3-dbus python3-gobject brightnessctl pactl

# 2. Create venv
python3 -m venv venv
source venv/bin/activate

# 3. Install package
pip install -e .

# 4. Install desktop file
cp com.layon.aiagent.desktop ~/.local/share/applications/
```

## Running

```bash
# System tray daemon (recommended)
./run.sh --tray

# CLI text mode
./run.sh

# CLI voice mode
./run.sh --voice

# Global hotkey listener only
./run.sh --hotkey
```

## Configuration

Edit `~/.config/ai-pc-agent/config.json` or use the Settings panel from the tray icon.

| Setting | Default | Description |
|---------|---------|-------------|
| `autonomy_mode` | `false` | Disables confirmations (opt-in only) |
| `voice_mode` | `false` | Use voice input by default |
| `gui_confirm` | `true` | Show GUI confirmation dialogs |
| `whisper_model` | `small` | Whisper model size |
| `llm_model` | `gemini-flash-latest` | Gemini model |
| `max_workers` | `3` | Baseline worker pool size |
| `max_fixers` | `2` | Baseline fixer pool size |
| `idle_grace_seconds` | `3600` | Idle timeout before scale-down |

## API Key

Set your Gemini API key:

```bash
export GEMINI_API_KEY="your_key_here"
```

Get a free key at: https://aistudio.google.com/apikey

## Global Hotkey

The agent registers Control+L via the xdg-desktop-portal GlobalShortcuts interface. This requires:
- The desktop file installed at `~/.local/share/applications/`
- A supported desktop environment (GNOME, KDE, etc.)
- Log out and back in after first install

## Architecture

```
┌─────────────────┐
│   System Tray   │
│   (pystray)     │
└────────┬────────┘
         │
    ┌────▼────┐
    │ Hotkey  │ (xdg-desktop-portal)
    │Listener │
    └────┬────┘
         │ user_request
    ┌────▼─────────┐
    │  Main Agent  │ (ZMQ PUB)
    │  (Coordinator)│
    └────┬─────────┘
         │ task_assign
    ┌────▼────┐
    │ Workers │ (ZMQ SUB)
    └─────────┘
         │
    ┌────▼────┐
    │ Fixers  │ (Self-healing)
    └─────────┘
```

### ECC-Inspired Enhancements

Built on the ECC (Everything Claude Code) architectural blueprint, ai-pc-agent
adds a portable, observable, and self-improving layer:

| Layer | Components | What it adds |
|-------|-----------|-------------|
| **Skills** | `skills/*/SKILL.md`, `skills_manager.py` | Contextually-loaded knowledge modules — only relevant skills activate per request instead of one monolithic prompt |
| **Observability** | `status.py` | JSON status payload (`context pressure`, `worker state`, `cost/risk`) at `~/.local/share/ai-pc-agent/status.json` |
| **Memory Vault** | `context_compactor.py` | Session summarization + persistent user preferences, recallable across restarts |
| **Self-Healing** | `trace_manager.py`, `playbooks/` | Failure traces auto-promote to repair playbooks after 3 occurrences — the supervisor consults them before restarting workers |
| **Security** | `security_audit.py` | Self-audit of tools, skills, and config for hardcoded secrets, unsafe patterns, and tier mismatches |

#### CLI Commands

```bash
python3 main.py --audit    # Run security self-audit
python3 main.py --status   # Print current agent status
python3 main.py            # CLI text mode (unchanged)
```

## Safety Model

- **Tier 1 (Safe):** Executes immediately (read_file, get_volume, etc.)
- **Tier 2 (Sensitive):** Requires confirmation by default (move_file, write_file, etc.)
- **Tier 3 (High-Risk):** Requires typed confirmation (shutdown, restart)
- **Full-Autonomy:** Opt-in only, disables confirmations with warning

## License

MIT
