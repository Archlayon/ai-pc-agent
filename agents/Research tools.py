"""
Research tools: web search + content extraction + report synthesis.

Used by ResearchWorker to answer open-ended "research this topic" tasks.

Pipeline:
  1. Tavily search API -> ranked result URLs + snippets (no scraping, no
     bot-block fights)
  2. Jina Reader (r.jina.ai) -> clean extracted text per URL (handles JS
     rendering + boilerplate stripping for free, no API key needed)
  3. Gemini (same model your main_agent already uses) -> synthesized report
     with inline [n] citations and a Sources section

Requires:
  TAVILY_API_KEY  - free tier at https://tavily.com
  GEMINI_API_KEY  - already required by main_agent.py
"""
import os
import re
import time

import requests

from settings import get_settings

TAVILY_URL = "https://api.tavily.com/search"
JINA_READER_PREFIX = "https://r.jina.ai/"

MAX_RESULTS = 5
MAX_CHARS_PER_SOURCE = 6000
FETCH_TIMEOUT = 20
DEFAULT_SAVE_DIR = os.path.expanduser("~/Documents")

_TOPIC_CLEANUP_PHRASES = [
    "give results in download",
    "save to downloads",
    "save to download",
    "and save to",
    "and give results",
    "in download",
    "to download",
]


def _clean_topic(topic: str) -> str:
    cleaned = topic.strip()
    lowered = cleaned.lower()
    for phrase in _TOPIC_CLEANUP_PHRASES:
        if phrase in lowered:
            cleaned = cleaned[:lowered.index(phrase)].strip()
            lowered = cleaned.lower()
    return cleaned


class ResearchError(Exception):
    pass


def _convert_to_docx(md_path: str) -> str | None:
    """Convert a markdown file to .docx using LibreOffice headless mode."""
    try:
        import subprocess
        out_dir = os.path.dirname(md_path) or "."
        subprocess.run(
            ["libreoffice", "--headless", "--convert-to", "docx", "--outdir", out_dir, md_path],
            check=True,
            timeout=60,
        )
        docx_path = os.path.splitext(md_path)[0] + ".docx"
        if os.path.exists(docx_path):
            return docx_path
    except Exception:
        pass
    return None


def _tavily_search(topic: str, max_results: int = MAX_RESULTS) -> list:
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        raise ResearchError("TAVILY_API_KEY not set")

    resp = requests.post(
        TAVILY_URL,
        json={
            "api_key": api_key,
            "query": topic,
            "max_results": max_results,
            "search_depth": "basic",
        },
        timeout=FETCH_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()

    return [
        {
            "title": r.get("title", "") or r.get("url", ""),
            "url": r.get("url", ""),
            "snippet": r.get("content", ""),
        }
        for r in data.get("results", [])
        if r.get("url")
    ]


def _fetch_clean_text(url: str, snippet_fallback: str = "") -> str:
    """Pull readable text out of a page via Jina Reader. Falls back to the
    search-result snippet if the fetch fails so one bad source doesn't sink
    the whole report."""
    try:
        resp = requests.get(
            JINA_READER_PREFIX + url,
            timeout=FETCH_TIMEOUT,
            headers={"X-Return-Format": "text"},
        )
        resp.raise_for_status()
        text = resp.text.strip()
        return text[:MAX_CHARS_PER_SOURCE] if text else snippet_fallback
    except Exception:
        return snippet_fallback


def _gather_sources(topic: str, max_results: int = MAX_RESULTS) -> list:
    cleaned_topic = _clean_topic(topic)
    results = _tavily_search(cleaned_topic, max_results=max_results)
    sources = []
    for r in results:
        text = _fetch_clean_text(r["url"], snippet_fallback=r["snippet"])
        if text:
            sources.append({"title": r["title"], "url": r["url"], "text": text})
    return sources


def _build_raw_report(topic: str, sources: list) -> str:
    parts = [
        f"# Research Report: {_clean_topic(topic)}",
        "",
        "**Generated:** " + __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "",
        "---",
        "",
        "_Note: Full synthesis was unavailable; raw extracted sources are included below._",
        "",
    ]
    for i, s in enumerate(sources, 1):
        parts.append(f"## Source [{i}]: {s['title']}")
        parts.append("")
        parts.append(f"**URL:** {s['url']}")
        parts.append("")
        parts.append(s["text"][:MAX_CHARS_PER_SOURCE])
        parts.append("")
        parts.append("---")
        parts.append("")
    return "\n".join(parts)


def _synthesize_report(topic: str, sources: list) -> str:
    from google import genai

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ResearchError("GEMINI_API_KEY not set")

    client = genai.Client(api_key=api_key)
    model = get_settings().get("llm_model", "gemini-flash-latest")
    fallback_model = "gemini-pro-latest" if "flash" in model else "gemini-flash-latest"

    source_block = "\n\n".join(
        f"SOURCE [{i + 1}] {s['title']} ({s['url']})\n{s['text']}"
        for i, s in enumerate(sources)
    )

    prompt = (
        f"Write a well-organized research report on: {_clean_topic(topic)}\n\n"
        "Use only the information in the sources below - do not invent facts. "
        "Cite claims inline using [1], [2], etc. matching the SOURCE numbers. "
        "Structure it with a short intro, a few thematic sections, and a "
        "closing summary. End with a 'Sources' section listing each numbered "
        "title and URL.\n\n"
        f"{source_block}"
    )

    last_err = None
    for attempt, current_model in enumerate([model, fallback_model] * 2, start=1):
        try:
            response = client.models.generate_content(model=current_model, contents=prompt)
            return response.text
        except Exception as e:
            last_err = e
            msg = str(e).lower()
            if "503" in msg or "unavailable" in msg or "429" in msg:
                wait = min(2 ** (attempt - 1), 16)
                time.sleep(wait)
                continue
            raise

    raise ResearchError(f"Gemini synthesis failed after retries: {last_err}")


def _resolve_save_path(save_path: str, topic: str) -> str:
    """Accepts either a folder (report gets an auto-generated filename inside
    it) or a full file path (used as-is)."""
    path = os.path.expanduser(save_path)
    _, ext = os.path.splitext(path)

    if ext.lower() in (".md", ".txt", ".markdown"):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        return path

    # treat as a folder
    os.makedirs(path, exist_ok=True)
    safe_topic = re.sub(r"[^\w\-]+", "_", topic.strip()).strip("_")[:60] or "research"
    filename = f"{safe_topic}_{int(time.time())}.md"
    return os.path.join(path, filename)


def research_topic(topic: str, max_results: int = MAX_RESULTS, save_path: str = None) -> str:
    """
    Full research pipeline: search -> extract -> synthesize -> save.

    Returns a status string (report saved to <path>) followed by the report
    itself, so the report is both on disk and visible in the chat response.
    Raises ResearchError if required API keys are missing.
    """
    sources = _gather_sources(topic, max_results=max_results)
    if not sources:
        return f"No usable sources found for '{topic}'."

    try:
        report = _synthesize_report(topic, sources)
    except ResearchError:
        report = _build_raw_report(topic, sources)

    final_path = _resolve_save_path(save_path or DEFAULT_SAVE_DIR, topic)
    try:
        with open(final_path, "w", encoding="utf-8") as f:
            f.write(report)
        header = f"Research report on '{topic}' saved to {final_path}\n\n"
        docx_path = _convert_to_docx(final_path)
        if docx_path:
            header += f"Word document saved to {docx_path}\n\n"
    except Exception as e:
        header = f"[warning] Could not save report to disk ({e})\n\n"

    return header + report