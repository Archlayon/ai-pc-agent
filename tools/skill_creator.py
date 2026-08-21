"""
Auto skill creator: research a topic and generate a SKILL.md file.
"""
from __future__ import annotations

import os
import re
import tempfile
import time

from audit_log import log_action

SKILLS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "skills")


def _slugify(name: str) -> str:
    name = name.lower().strip()
    name = re.sub(r"[^a-z0-9]+", "-", name)
    name = re.sub(r"-+", "-", name).strip("-")
    return name or "skill"


def _load_research(topic: str, max_results: int = 5) -> str:
    from tools.research_tools import research_topic
    with tempfile.TemporaryDirectory() as tmpdir:
        result = research_topic(topic, max_results=max_results, save_path=tmpdir)
        return result


def _synthesize_skill_md(topic: str, research_text: str, skill_name: str) -> str:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set")

    from google import genai
    client = genai.Client(api_key=api_key)
    model = "gemini-flash-latest"
    fallback_model = "gemini-pro-latest"

    prompt = f"""You are an expert at creating AI agent skill definitions.

Based on the research below about "{topic}", generate a complete SKILL.md file for the AI PC Agent skill system.

Rules:
1. The frontmatter `name` must be: {skill_name}
2. `description` should be a concise summary of what the skill covers
3. `tags` should be a list of relevant keywords (lowercase)
4. `risk` must be one of: low, medium, high
5. `origin` should be: ai-pc-agent
6. Body must include these sections:
   - ## When to Activate (bullet list of user phrases that should trigger this skill)
   - ## Core Concepts (key ideas, terminology, how the agent should think about this domain)
   - ## Workflow or ## Best Practices (actionable guidance)
   - ## Code Examples (concrete Python examples if applicable)
7. If the domain requires execution tooling that doesn't exist yet, include `requires_tooling: true` in frontmatter and note what tools would be needed
8. Keep the total file under 4000 characters
9. Output ONLY the markdown content, no explanations before or after

Research material:
{research_text[:12000]}
"""

    last_err = None
    for attempt, current_model in enumerate([model, fallback_model] * 3, start=1):
        try:
            response = client.models.generate_content(model=current_model, contents=prompt)
            text = response.text.strip()
            if text.startswith("```"):
                text = re.sub(r"^```(?:markdown)?\n?", "", text)
                text = re.sub(r"\n?```$", "", text)
            return text.strip()
        except Exception as e:
            last_err = e
            msg = str(e).lower()
            if "503" in msg or "unavailable" in msg or "429" in msg:
                wait = min(2 ** (attempt - 1), 16)
                time.sleep(wait)
                continue
            raise

    return _fallback_skill_md(topic, skill_name, research_text, last_err)


def _fallback_skill_md(topic: str, skill_name: str, research_text: str, error: Exception) -> str:
    """Generate a basic SKILL.md from research when the LLM is unavailable."""
    error_msg = str(error).replace('"', "'")

    sentences = re.split(r"(?<=[.!?])\s+", research_text)
    good_sentences = []
    seen = set()
    for s in sentences:
        s = s.strip()
        if not s or len(s) < 40:
            continue
        if s.startswith("#") or s.startswith("---") or s.startswith("**") or s.startswith("Source") or s.startswith("URL") or s.startswith("Generated") or s.startswith("convert") or s.startswith("[") or s.startswith("INIT") or s.startswith("FETCH") or s.startswith("SCRAPE") or s.startswith("COMPLETE"):
            continue
        if "http" in s or ".md" in s or "Word document" in s:
            continue
        key = s[:60]
        if key in seen:
            continue
        seen.add(key)
        good_sentences.append(s)
        if len(good_sentences) >= 10:
            break

    concepts_md = "\n".join(f"- {s}" for s in good_sentences[:6])

    body = f"""## When to Activate

- User asks about "{topic}"
- User mentions related keywords from this domain
- User asks for help, explanation, or guidance related to {topic}

## Core Concepts

{concepts_md if concepts_md else f"- Key concepts and terminology related to {topic}"}

## Best Practices

- Use the research sources to ground answers in real information
- Cite sources when possible
- If execution is needed, check if appropriate tools exist first
- If no tools exist for this domain, inform the user that tooling may need to be built

## Code Examples

```python
# Example usage will depend on available tools for this domain
# If no tools exist yet, the agent can only provide knowledge-based assistance
```
"""

    frontmatter = f"""---
name: {skill_name}
description: Knowledge skill about {topic} - auto-generated from research
tags: [{skill_name.replace('-', ', ')}, knowledge]
risk: low
origin: auto-generated
requires_tooling: true
---

"""

    return frontmatter + body


def _ensure_skill_dir(skill_name: str) -> str:
    skill_dir = os.path.join(SKILLS_DIR, skill_name)
    os.makedirs(skill_dir, exist_ok=True)
    return skill_dir


def _validate_frontmatter(content: str, skill_name: str) -> tuple[bool, str]:
    if not content.startswith("---"):
        return False, "Missing YAML frontmatter start (---)"

    parts = content.split("---", 2)
    if len(parts) < 3:
        return False, "Missing YAML frontmatter end (---)"

    frontmatter_text = parts[1]
    name_match = re.search(r"^name:\s*(.+)", frontmatter_text, re.MULTILINE)
    if not name_match:
        return False, "Missing 'name' in frontmatter"

    name = name_match.group(1).strip().strip('"').strip("'")
    if not re.match(r"^[a-z0-9]+(-[a-z0-9]+)*$", name):
        return False, f"Skill name '{name}' may only contain lowercase letters, numbers, and hyphens"

    if name != skill_name:
        return False, f"Frontmatter name '{name}' does not match expected '{skill_name}'"

    return True, "OK"


def create_skill_from_research(topic: str, skill_name: str = "") -> str:
    """Research a topic and generate a SKILL.md file.

    Args:
        topic: The topic to research and create a skill for
        skill_name: Optional skill name slug. If empty, derived from topic.

    Returns:
        Status string with path to created skill.
    """
    topic = topic.strip()
    if not topic:
        return "[error] Empty topic"

    skill_name = skill_name.strip() or _slugify(topic)
    skill_name = _slugify(skill_name)

    log_action("create_skill_from_research", {"topic": topic, "skill_name": skill_name}, "approved", "Starting skill creation")

    research_text = _load_research(topic, max_results=5)
    if not research_text or research_text.startswith("[error]"):
        return f"[error] Research failed: {research_text}"

    try:
        skill_content = _synthesize_skill_md(topic, research_text, skill_name)
    except Exception as e:
        return f"[error] Skill synthesis failed: {e}"

    valid, msg = _validate_frontmatter(skill_content, skill_name)
    if not valid:
        return f"[error] Generated skill has invalid frontmatter: {msg}"

    skill_dir = _ensure_skill_dir(skill_name)
    skill_path = os.path.join(skill_dir, "SKILL.md")

    try:
        with open(skill_path, "w", encoding="utf-8") as f:
            f.write(skill_content)
    except Exception as e:
        return f"[error] Could not write skill file: {e}"

    try:
        from skills_manager import load_all_skills
        load_all_skills.cache_clear() if hasattr(load_all_skills, "cache_clear") else None
    except Exception:
        pass

    log_action("create_skill_from_research", {"topic": topic, "skill_name": skill_name}, "approved", f"Skill created at {skill_path}")

    requires_tooling = "requires_tooling: true" in skill_content
    tooling_note = ""
    if requires_tooling:
        tooling_note = "\n\nNote: This skill requires_tooling: true. You may need to build Python tooling for the agent to execute actions in this domain."

    return f"Skill created: {skill_path}\nName: {skill_name}\nRequires tooling: {requires_tooling}{tooling_note}"
