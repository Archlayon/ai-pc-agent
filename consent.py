"""
Layered consent management for the AI PC Agent.

Handles contextual risk prompts, category-specific copy, and high-risk
deliberate-action requirements.
"""
from settings import get_settings


TIER_SAFE = 1
TIER_SENSITIVE = 2
TIER_HIGH_RISK = 3


CONSENT_COPY = {
    "install_time": (
        "AI PC Agent can open apps, move files, change settings, access the webcam on-demand, "
        "and more. Actions may be confirmed before running. Full autonomy mode is opt-in only "
        "and disables confirmations — changes may be irreversible."
    ),
    "feature_time": (
        "You are enabling a feature that involves risk. Please review the details below before continuing."
    ),
    "autonomy_opt_in": (
        "Full-autonomy mode disables confirmations. Changes may be irreversible. "
        "This is an opt-in setting. Type 'I understand' to enable."
    ),
    "module_install": (
        "This will install a new system-level capability: {name}. "
        "It can modify files and system settings. Type 'approve' to continue."
    ),
    "knowledge_skill": (
        "Knowledge skill '{name}' will be enabled. "
        "This does not grant new system access, but information accuracy is not guaranteed."
    ),
    "sensitive_action": (
        "About to run: {tool_name} with {args}. "
        "This action may modify or delete data. Confirm?"
    ),
    "high_risk": (
        "This is a high-risk action: {tool_name}. "
        "It can power off or restart your PC, or make system-level changes. "
        "Type the tool name exactly to confirm."
    ),
    "webcam": (
        "The webcam will be accessed on-demand for this action only. "
        "It will not run silently in the background. Confirm?"
    ),
    "email_send": (
        "This agent creates email drafts only. Sending requires your manual approval. "
        "Drafts are stored locally for your review."
    ),
}


def request_consent(category: str, **kwargs) -> bool:
    settings = get_settings()

    if settings.get("autonomy_mode", False):
        if category == "sensitive_action":
            return True
        if category in ("module_install", "high_risk"):
            return False

    prompt = CONSENT_COPY.get(category, "Confirm action?").format(**kwargs)

    if category in ("autonomy_opt_in", "module_install", "high_risk"):
        print(f"\n[consent] {prompt}")
        answer = input("> ").strip().lower()
        if category == "high_risk":
            return answer == kwargs.get("tool_name", "").lower()
        return answer in ("i understand", "approve", "yes")

    if category == "install_time":
        print(f"\n[consent] {prompt}")
        answer = input("Type 'accept' to continue: ").strip().lower()
        return answer == "accept"

    print(f"\n[confirm] {prompt} [y/N] ", end="")
    answer = input().strip().lower()
    return answer == "y"
