---
name: app_launch
description: Application launching — desktop entries, Flatpak, Snap, PATH lookup, web apps
tags: [file, safe]
risk: low
origin: ai-pc-agent
---

# App Launch Skill

## When to Activate

- User asks to "open" or "launch" an application
- User asks to open a website by name (youtube, github, etc.)
- User asks to open a file with a specific application

## Core Concepts

### Name Normalization

Strip articles (a, an, the) and generic suffixes (app, application, program, software, player, media player).

Common aliases:
- "google chrome" → "chrome"
- "chromium" → "chrome"
- "visual studio code" → "vscode"
- "vs code" → "vscode"
- "libre office" → "libreoffice"
- "ms teams" → "teams"
- "microsoft teams" → "teams"

### Launch Strategy (in priority order)

1. **Flatpak** — `flatpak run <id>`
2. **Desktop entry** — `gtk-launch <name>`
3. **Binary** — direct exec if path exists
4. **exec_line** — from .desktop file
5. **path** — from .desktop file

Try each method; report success on the first one that works. If all fail,
fall back to web search or file finder.

### Web Apps

If the app name matches a known web service, open the URL directly:
youtube → https://www.youtube.com
github → https://github.com
etc.

### Already Running

If the app is already running, return a message instead of launching a second instance.

### File with Specific App

If user says "open X with Y" or "open X in Y":
1. Resolve the file path (try raw, then find_file)
2. Resolve the app name (normalize)
3. Launch with the app using Flatpak/binary/exec_line

## Code Examples

```python
# Open an app
_open_app("firefox")

# Open a website
_open_url("youtube")

# Open a file in a specific app
_open_file_with_app("/path/to/file.pdf", "libreoffice")
```

## Best Practices

- Check if app is already running before launching
- Verify process started successfully after launch
- Prefer user-installed apps over system paths
- Always try web app fallback for known services
