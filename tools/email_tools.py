"""
Email tools for the AI PC Agent.

Draft-and-hold workflow: creates a draft email file for user review
before sending. Never sends automatically.
"""
import os
import uuid
from datetime import datetime, timezone

from audit_log import log_action

DRAFTS_DIR = os.path.expanduser("~/.local/share/ai-pc-agent/drafts")


def _ensure_drafts_dir():
    os.makedirs(DRAFTS_DIR, exist_ok=True)


def draft_email(to: str, subject: str, body: str) -> str:
    _ensure_drafts_dir()
    draft_id = str(uuid.uuid4())[:8]
    timestamp = datetime.now(timezone.utc).isoformat()
    filename = f"draft_{draft_id}.eml"
    filepath = os.path.join(DRAFTS_DIR, filename)

    content = f"""From: AI PC Agent <agent@local>
To: {to}
Subject: {subject}
Date: {timestamp}
Message-ID: <{draft_id}@ai-pc-agent>

{body}
"""

    with open(filepath, "w") as f:
        f.write(content)

    log_action("draft_email", {"to": to, "subject": subject}, "approved", f"Draft saved to {filepath}")
    return f"Draft email saved to {filepath}. Review and send manually."


def list_drafts() -> str:
    _ensure_drafts_dir()
    files = sorted(os.listdir(DRAFTS_DIR))
    if not files:
        return "No email drafts found."
    return "\n".join(files)


def send_email(to: str, subject: str, body: str) -> str:
    return "[error] Sending emails directly is disabled in this version. Use draft_email to create a draft for manual review."
