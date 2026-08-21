"""
GIMP design agent tools: natural-language design requests -> GIMP poster/image creation.

Orchestrates asset downloading, composition planning, and GIMP batch operations.
"""
from __future__ import annotations

import os
import re
import tempfile

from audit_log import log_action

from tools.gimp_tools import gimp_batch_operation


def _download_image(url: str, dest_path: str) -> str:
    import requests
    try:
        resp = requests.get(url, timeout=30, headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })
        resp.raise_for_status()
        os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
        with open(dest_path, "wb") as f:
            f.write(resp.content)
        return dest_path
    except Exception as e:
        return f"[error] Download failed: {e}"


def _extract_title_subtitle(request: str, default_title: str = "", default_subtitle: str = "") -> tuple[str, str]:
    text = request.strip()
    title = default_title
    subtitle = default_subtitle

    if "called" in text.lower():
        parts = text.split("called", 1)[1].strip()
        if "and" in parts.lower():
            parts = parts.split("and", 1)[0].strip()
        if "radio show" in parts.lower():
            title = parts.split("radio show", 1)[0].strip()
            subtitle = "Radio Show"
        elif "podcast" in parts.lower():
            title = parts.split("podcast", 1)[0].strip()
            subtitle = "Podcast"
        else:
            title = parts.strip()
    elif "for a " in text.lower() or "for an " in text.lower():
        lowered = text.lower()
        for prefix in ["for a ", "for an "]:
            idx = lowered.find(prefix)
            if idx != -1:
                rest = text[idx + len(prefix):].strip()
                words = rest.split()
                if words:
                    title = words[0]
                    subtitle = " ".join(words[1:]) if len(words) > 1 else ""
                break
    elif "for" in text.lower() and "radio" in text.lower():
        idx = text.lower().index("for")
        title = text[idx + 3:].strip()
        if "radio" in title.lower():
            title = re.sub(r"radio\s+show", "", title, flags=re.IGNORECASE).strip()
        subtitle = "Radio Show"

    if not title:
        title = default_title or "Untitled"
    if not subtitle:
        subtitle = default_subtitle or ""

    return title, subtitle


def design_with_gimp(request: str, output_path: str = "") -> str:
    """Design an image/poster using GIMP from natural language.

    Handles asset downloading, composition, and GIMP batch operations.
    """
    title, subtitle = _extract_title_subtitle(request)

    if not output_path:
        output_path = os.path.join(os.path.expanduser("~/Downloads"), f"{title.lower().replace(' ', '_')}_poster.png")

    output_path = os.path.expanduser(output_path)
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    asset_urls = []
    request_lower = request.lower()
    if "coffee" in request_lower:
        asset_urls.append("https://cdn-icons-png.flaticon.com/512/833/833314.png")
    if "sunrise" in request_lower or "morning" in request_lower:
        asset_urls.append("https://images.unsplash.com/photo-1470252649378-9c29740c9fa8?w=1080&q=80")
    if "music" in request_lower or "podcast" in request_lower:
        asset_urls.append("https://cdn-icons-png.flaticon.com/512/727/727399.png")

    downloaded_assets = []
    if asset_urls:
        for idx, url in enumerate(asset_urls):
            ext = os.path.splitext(url.split("?")[0])[1].lower() or ".png"
            dest = os.path.join(tempfile.gettempdir(), f"gimp_design_asset_{os.getpid()}_{idx}{ext}")
            result = _download_image(url, dest)
            if not result.startswith("[error]"):
                downloaded_assets.append(result)

    result = gimp_batch_operation(
        "create_poster",
        output_path=output_path,
        title=title,
        subtitle=subtitle,
        width=1080,
        height=1920,
        background_color="#1a1a2e",
        title_color="#ffffff",
        subtitle_color="#e94560",
        asset_urls=downloaded_assets if downloaded_assets else None,
    )

    log_action("design_with_gimp", {"request": request, "output": output_path, "assets": len(downloaded_assets)}, "approved", result)
    return result
