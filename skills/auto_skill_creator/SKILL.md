"""
Skill creator: turns a capability gap into a new SKILL.md by researching the
topic and synthesizing it into skill-doc format.

Matches the workflow in the auto-skill-creator SKILL.md:
  1. research_topic (already registered) gathers a report
  2. create_skill_from_research synthesizes that report into a SKILL.md and
     saves it under skills/<skill-name>/SKILL.md

This is intentionally a single self-contained call rather than a two-step
LLM-orchestrated chain: main_agent currently dispatches one function call
and doesn't loop the result back to the LLM for a follow-up decision, so if
`research_report` isn't supplied, create_skill_from_research gathers its own
sources internally (reusing research_tools' search+extract step) instead of
requiring an agentic loop that doesn't exist yet. If a report IS supplied
(e.g. once that loop gets built), it's used directly and no new search runs.

Only produces the *knowledge* half of a skill. If the domain requires new
automation (not just instructions), the frontmatter sets
`requires_tooling: true` with a `tooling_note` explaining what's missing,
rather than silently pretending a knowledge doc is enough.
"""
import os
import re
import time

from settings import get_settings
from tools.research_tools import _gather_sources, ResearchError

SKILLS_SUBDIR_DEFAULT = "skills"
MAX_RESULTS_PER_TOPIC = 4
MAX_SKILL_CHARS = 4000


class SkillCreationError(Exception):
    pass


def _skills_dir() -> str:
    return os.path.expanduser(get_settings().get("skills_dir", SKILLS_SUBDIR_DEFAULT))


def _slugify(name: str) -> str:
    slug = re.sub(r"[^\w\-]+", "-", name.strip().lower()).strip("-")
    slug = re.sub(r"-+", "-", slug)
    return slug or f"skill-{int(time.time())}"


def _gather_all_sources(topic: str, subtopics: list) -> list:
    all_sources = []
    seen_urls = set()
    for t in [topic, *(subtopics or [])]:
        try:
            sources = _gather_sources(t, max_results=MAX_RESULTS_PER_TOPIC)
        except ResearchError:
            continue
        for s in sources:
            if s["url"] not in seen_urls:
                seen_urls.add(s["url"])
                all_sources.append(s)
    return all_sources


def _synthesize_skill_doc(topic: str, skill_name: str, material: str) -> str:
    from google import genai

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise SkillCreationError("GEMINI_API_KEY not set")

    client = genai.Client(api_key=api_key)
    model = get_settings().get("llm_model", "gemini-flash-latest")

    prompt = f"""You are writing a SKILL.md file for an AI agent, teaching it how to help
a user with: {topic}

Base the content only on the research material below -- do not invent facts,
tool names, or APIs that don't exist. Output ONLY the file content in
exactly this format, nothing before or after it, and keep the ENTIRE output
under {MAX_SKILL_CHARS} characters:

---
name: {skill_name}
description: <one line: what this covers and when to activate it>
tags: [<3-6 relevant lowercase tags>]
risk: <low, medium, or high -- based on whether following this could cause
  real-world harm if done wrong, e.g. financial loss or safety issues>
origin: ai-pc-agent-autogen
requires_tooling: <true or false -- true only if actually DOING this (not
  just advising on it) needs new automation/tool code beyond conversation,
  e.g. a broker-connected trading tool, driving a specific application, an
  API integration>
tooling_note: <if requires_tooling is true, one sentence on what tool would
  be needed; otherwise omit this line entirely>
---

# <Human-readable title>

## When to Activate
<bullet list of user phrasings/intents that should trigger this skill>

## Core Concepts
<key ideas and terminology someone needs to understand this domain>

## Best Practices
<concrete, actionable guidance -- steps, rules of thumb, common mistakes>

RESEARCH MATERIAL:
{material}
"""

    response = client.models.generate_content(model=model, contents=prompt)
    return response.text.strip()


def _requires_tooling(skill_md: str) -> bool:
    match = re.search(r"^requires_tooling:\s*(true|false)", skill_md, re.MULTILINE | re.IGNORECASE)
    return bool(match and match.group(1).lower() == "true")


def _tooling_note(skill_md: str) -> str:
    match = re.search(r"^tooling_note:\s*(.+)$", skill_md, re.MULTILINE)
    return match.group(1).strip() if match else ""


def create_skill_from_research(
    topic: str,
    skill_name: str = None,
    research_report: str = None,
    subtopics: list = None,
) -> str:
    """
    Synthesizes a SKILL.md for `topic` and saves it to
    skills/<skill-name>/SKILL.md.

    If `research_report` is provided, it's used directly as the source
    material (step-2-of-a-chain case). Otherwise this gathers sources itself
    the same way research_topic does (self-contained single-call case).

    Returns a status string: save location, plus a tooling note if the
    skill's frontmatter says requires_tooling: true.
    """
    if not topic or not topic.strip():
        return "[error] No topic provided for skill creation"

    slug = _slugify(skill_name or topic)

    if research_report and research_report.strip():
        material = research_report.strip()
    else:
        sources = _gather_all_sources(topic, subtopics)
        if not sources:
            return f"No usable sources found for '{topic}' -- could not create a skill."
        material = "\n\n".join(
            f"SOURCE [{i + 1}] {s['title']} ({s['url']})\n{s['text']}"
            for i, s in enumerate(sources)
        )

    skill_md = _synthesize_skill_doc(topic, slug, material)

    if len(skill_md) > MAX_SKILL_CHARS:
        skill_md = skill_md[:MAX_SKILL_CHARS].rstrip() + "\n"

    skill_dir = os.path.join(_skills_dir(), slug)
    os.makedirs(skill_dir, exist_ok=True)
    skill_path = os.path.join(skill_dir, "SKILL.md")

    with open(skill_path, "w", encoding="utf-8") as f:
        f.write(skill_md)

    result = f"Created new skill '{slug}' at {skill_path}"
    if _requires_tooling(skill_md):
        note = _tooling_note(skill_md)
        result += (
            f"\n\n[tooling needed] This skill covers the knowledge, but "
            f"doing this (not just advising on it) needs new tool code"
            + (f": {note}" if note else ".")
            + " Want me to scope that out separately?"
        )
    return result