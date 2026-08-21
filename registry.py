"""
Trusted module registry for capability acquisition.

New executable skills are vetted and stored here. The main agent references
this registry when deciding whether to allow capability acquisition.
"""
import json
import os

REGISTRY_DIR = os.path.expanduser("~/.local/share/ai-pc-agent")
REGISTRY_PATH = os.path.join(REGISTRY_DIR, "registry.json")


def _ensure_registry():
    os.makedirs(REGISTRY_DIR, exist_ok=True)
    if not os.path.exists(REGISTRY_PATH):
        with open(REGISTRY_PATH, "w") as f:
            json.dump({"modules": []}, f, indent=2)
    return REGISTRY_PATH


def load_registry():
    _ensure_registry()
    with open(REGISTRY_PATH, "r") as f:
        return json.load(f)


def save_registry(data: dict):
    with open(REGISTRY_PATH, "w") as f:
        json.dump(data, f, indent=2)


def register_module(name: str, description: str, source: str, risk: str = "medium", approved: bool = False):
    data = load_registry()
    module = {
        "name": name,
        "description": description,
        "source": source,
        "risk": risk,
        "approved": approved,
        "added_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
    }
    data["modules"].append(module)
    save_registry(data)
    return module


def is_module_approved(name: str) -> bool:
    data = load_registry()
    for m in data.get("modules", []):
        if m["name"] == name:
            return m.get("approved", False)
    return False


_ensure_registry()
if not is_module_approved("gimp-automation"):
    register_module(
        name="gimp-automation",
        description="Automate GIMP batch operations (resize, filters, format conversion)",
        source="skills/gimp-automation/SKILL.md",
        risk="medium",
        approved=True,
    )
