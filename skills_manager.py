"""
Skills manager for the AI PC Agent.

Loads YAML-frontmattered Markdown skill files from skills/*/SKILL.md,
matches them against the user's query by tag/keyword, and injects the
relevant skill content into the LLM system prompt.

This is the ECC-inspired "contextual knowledge" layer: instead of one
monolithic prompt, only the skills relevant to the current task are loaded.
The existing SYSTEM_INSTRUCTION is preserved as the base; skills are appended
as additional context.
"""
import os
import re
import yaml

SKILLS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "skills")
MAX_SKILL_CONTEXT_CHARS = 4000  # don't let skills dominate the context


def _parse_frontmatter(content: str) -> dict:
    """Extract YAML frontmatter from a Markdown file."""
    if not content.startswith("---"):
        return {}
    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}
    try:
        return yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        return {}


def _strip_frontmatter(content: str) -> str:
    """Remove YAML frontmatter, return the Markdown body."""
    if not content.startswith("---"):
        return content
    parts = content.split("---", 2)
    if len(parts) < 3:
        return content
    return parts[2].strip()


def load_all_skills() -> list[dict]:
    """Load all skill definitions from the skills directory.

    Returns a list of dicts: {name, description, tags, risk, body, origin}
    """
    skills = []
    if not os.path.isdir(SKILLS_DIR):
        return skills

    for entry in sorted(os.listdir(SKILLS_DIR)):
        skill_dir = os.path.join(SKILLS_DIR, entry)
        skill_file = os.path.join(skill_dir, "SKILL.md")
        if not os.path.isfile(skill_file):
            continue

        try:
            with open(skill_file, "r") as f:
                raw = f.read()
        except Exception:
            continue

        meta = _parse_frontmatter(raw)
        body = _strip_frontmatter(raw)

        skills.append({
            "name": meta.get("name", entry),
            "description": meta.get("description", ""),
            "tags": meta.get("tags", []),
            "risk": meta.get("risk", "unknown"),
            "origin": meta.get("origin", "ai-pc-agent"),
            "body": body,
        })

    return skills


# Keyword trigger maps per skill name. These are the actual activation
# keywords that determine when a skill's content gets injected.
SKILL_KEYWORDS = {
    "file_management": [
        "move", "copy", "rename", "file", "find file", "directory",
        "read file", "write file", "edit", "append to", "delete file",
    ],
    "research_workflow": [
        "research", "study", "investigate", "tell me about",
        "what is", "how does", "information about", "scrape",
        "search the web", "find information",
    ],
    "system_control": [
        "brightness", "volume", "shutdown", "restart", "power off",
        "battery", "cpu", "memory", "disk", "play media", "webcam",
        "kill shut", "cancel shut",
    ],
    "app_launch": [
        "open", "launch", "start", "run app", "firefox", "chrome",
        "vscode", "discord", "spotify", "youtube", "github",
    ],
    "gimp-automation": [
        "gimp", "image editor", "batch process", "apply filter",
        "resize images", "convert image", "edit photo", "photo edit",
        "batch edit", "process images", "gimp filter", "design a poster",
        "create poster", "make poster", "radio show poster",
    ],
    "auto-skill-creator": [
        "create a skill", "make a skill", "add a skill", "generate a skill",
        "build a skill", "new skill", "skill about", "research and make skill",
    ],
    "gimp-designer": [
        "design a poster", "create a poster", "make a poster", "design a flyer",
        "create a flyer", "make a banner", "design a banner", "create a banner",
        "design with gimp", "gimp design", "graphic design",
    ],
}


def match_skills(query: str, all_skills: list[dict] | None = None) -> list[dict]:
    """Return skills whose tags or keywords match the user's query.

    Matching strategy:
    1. Check keyword triggers (case-insensitive substring).
    2. Check tag overlap (query tokens vs skill tags).
    3. Always include 'tags: [safe]' skills if no strong match (fallback safety).
    """
    if all_skills is None:
        all_skills = load_all_skills()

    query_lower = query.lower().strip()
    matched = []
    seen_names = set()

    # Keyword-based matching
    for skill in all_skills:
        skill_name = skill["name"]
        keywords = SKILL_KEYWORDS.get(skill_name, [])
        for kw in keywords:
            if kw in query_lower:
                if skill_name not in seen_names:
                    matched.append(skill)
                    seen_names.add(skill_name)
                break

    # Tag-based matching: if query mentions a tag word
    query_tokens = set(re.findall(r"\w+", query_lower))
    for skill in all_skills:
        skill_name = skill["name"]
        if skill_name in seen_names:
            continue
        skill_tags = set(skill.get("tags", []))
        if skill_tags and skill_tags & query_tokens:
            matched.append(skill)
            seen_names.add(skill_name)

    # If nothing matched, include low-risk skills as context
    if not matched:
        for skill in all_skills:
            if skill["risk"] in ("low", "medium") and skill["name"] not in seen_names:
                matched.append(skill)
                seen_names.add(skill["name"])

    return matched


def build_skill_context(matched_skills: list[dict]) -> str:
    """Assemble skill bodies into a single string for injection into the prompt.

    Truncates if total exceeds MAX_SKILL_CONTEXT_CHARS to stay within
    token budget while preserving the most relevant skills first.
    """
    parts = []
    total = 0

    for skill in matched_skills:
        header = f"\n--- SKILL: {skill['name']} ({skill['risk']} risk)\n"
        body = skill["body"] or ""
        chunk = header + body
        if total + len(chunk) > MAX_SKILL_CONTEXT_CHARS and parts:
            break
        parts.append(chunk)
        total += len(chunk)

    if not parts:
        return ""
    return "\n## Relevant Skills Context\n" + "".join(parts)


def get_system_prompt(user_query: str, base_instruction: str = "") -> tuple[str, list[str]]:
    """Build the full system prompt by combining the base instruction
    with only the skills relevant to the user's query.

    Returns (full_prompt, matched_skill_names).
    """
    all_skills = load_all_skills()
    matched = match_skills(user_query, all_skills)
    skill_context = build_skill_context(matched)

    prompt = base_instruction
    if skill_context:
        prompt = prompt + skill_context

    return prompt, [s["name"] for s in matched]


# Self-test
if __name__ == "__main__":
    test_queries = [
        "open firefox",
        "research quantum computing",
        "move this file to Documents",
        "what's the battery status",
        "find budget.xlsx",
        "hello how are you",
    ]

    print("=== Skill matching test ===")
    for q in test_queries:
        names = []
        # Reload each time to keep it fresh
        all_skills = load_all_skills()
        matched = match_skills(q, all_skills)
        names = [s["name"] for s in matched]
        print(f"  '{q}' → {names}")

    print(f"\nTotal skills loaded: {len(load_all_skills())}")
