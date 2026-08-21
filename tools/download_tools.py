"""
Download tools for the AI PC Agent.

Download files from URLs to a local path.
"""
import os
import urllib.request
from urllib.parse import urlparse

from audit_log import log_action

DOWNLOADS_DIR = os.path.expanduser("~/Downloads")


def download_file(url: str, destination: str = "") -> str:
    try:
        if not destination:
            parsed = urlparse(url)
            filename = os.path.basename(parsed.path) or "downloaded_file"
            destination = os.path.join(DOWNLOADS_DIR, filename)

        destination = os.path.expanduser(destination)
        os.makedirs(os.path.dirname(destination) or ".", exist_ok=True)

        urllib.request.urlretrieve(url, destination)
        log_action("download_file", {"url": url, "destination": destination}, "approved", f"Downloaded to {destination}")
        return f"Downloaded to {destination}"
    except Exception as e:
        return f"[error] Download failed: {e}"
