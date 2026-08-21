"""
Research tools for the AI PC Agent.

Open-ended internet research reports via web search + synthesis.
"""
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from audit_log import log_action

try:
    import requests

    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

from research_scraper import (
    normalize_search_results,
    curate_sources,
    scrape_page,
    _search_web,
)
from retrievers import get_retriever, Retriever
from prompts import get_prompt_family

RESEARCH_WORKER_URL = os.environ.get("RESEARCH_WORKER_URL", "tcp://127.0.0.1:5556")

REPORTS_DIR = os.path.expanduser("~/.local/share/ai-pc-agent/reports")


def _ensure_reports_dir():
    os.makedirs(REPORTS_DIR, exist_ok=True)


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


def _resolve_save_path(save_path: str) -> str:
    if not save_path:
        return ""
    save_path = save_path.strip().rstrip("/")
    common = {
        "downloads": os.path.expanduser("~/Downloads"),
        "download": os.path.expanduser("~/Downloads"),
        "documents": os.path.expanduser("~/Documents"),
        "document": os.path.expanduser("~/Documents"),
        "desktop": os.path.expanduser("~/Desktop"),
        "pictures": os.path.expanduser("~/Pictures"),
        "videos": os.path.expanduser("~/Videos"),
        "music": os.path.expanduser("~/Music"),
    }
    lower = save_path.lower()
    if lower in common:
        return common[lower]
    words = re.findall(r"[a-zA-Z]+", lower)
    for word in words:
        if word in common:
            return common[word]
    return os.path.expanduser(os.path.expandvars(save_path))


def _try_worker_research(query: str, max_results: int, save_path: str) -> dict | None:
    try:
        import zmq
        ctx = zmq.Context()
        socket = ctx.socket(zmq.REQ)
        socket.setsockopt(zmq.LINGER, 0)
        socket.setsockopt(zmq.RCVTIMEO, 1500)
        socket.setsockopt(zmq.SNDTIMEO, 1000)
        socket.connect(RESEARCH_WORKER_URL)

        payload = {
            "type": "DEEP_RESEARCH",
            "query": query,
            "save_path": save_path,
            "max_results": max_results,
        }
        socket.send_json(payload)
        response = socket.recv_json()
        socket.close()
        ctx.term()
        return response
    except Exception:
        return None


def _run_research_inline(topic: str, max_results: int = 5, save_path: str = "") -> str:
    _ensure_reports_dir()
    query = topic.strip()
    if not query:
        return "[error] Empty research topic"

    cleanup_phrases = [
        "give results in download",
        "save to downloads",
        "save to download",
        "and save to",
        "and give results",
        "in download",
        "to download",
    ]
    cleaned = query
    lowered = cleaned.lower()
    for phrase in cleanup_phrases:
        if phrase in lowered:
            cleaned = cleaned[:lowered.index(phrase)].strip()
            lowered = cleaned.lower()

    retriever_names = os.environ.get("RESEARCH_RETRIEVERS", "duckduckgo,wikipedia").split(",")
    retrievers: list[Retriever] = [get_retriever(name.strip()) for name in retriever_names if name.strip()]

    import asyncio

    async def _search_all() -> list[dict]:
        coros = [r.search(cleaned, max_results=max_results) for r in retrievers]
        results = await asyncio.gather(*coros, return_exceptions=True)
        merged: list[dict] = []
        seen: set[str] = set()
        for result in results:
            if isinstance(result, Exception) or not result:
                continue
            for item in result:
                url = item.get("href") or item.get("url") or ""
                if url and url in seen:
                    continue
                if url:
                    seen.add(url)
                merged.append(item)
        return merged

    raw_results = asyncio.run(_search_all())
    search_results = normalize_search_results(raw_results)

    session_name = f"{query.replace(' ', '_').replace('/', '_')}"
    session_dir = os.path.join(REPORTS_DIR, f"{session_name}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}")
    os.makedirs(session_dir, exist_ok=True)

    resolved_save = _resolve_save_path(save_path)
    if resolved_save and os.path.isdir(resolved_save):
        output_dir = resolved_save
    else:
        output_dir = session_dir

    assets_dir = os.path.join(output_dir, "assets")
    os.makedirs(assets_dir, exist_ok=True)

    visited_urls: set[str] = set()

    pages: list[dict] = []
    for r in search_results:
        url = r.get("url", "")
        if not url:
            continue
        page = scrape_page(url, Path(output_dir), visited_urls=visited_urls)
        if page:
            pages.append(page)
        if len(pages) >= max_results:
            break

    curated_pages = curate_sources(query, pages) if pages else []

    compiled_md: list[str] = [
        f"# Research Report: {query}",
        f"",
        f"**Generated:** {datetime.now(timezone.utc).isoformat()}",
        f"",
        "---",
        "",
    ]

    if not curated_pages and not search_results:
        search_url = f"https://www.google.com/search?q={query.replace(' ', '+')}"
        compiled_md.append("_SEARCH_FAILED_")
        compiled_md.append("")
        compiled_md.append(f"_Background search returned 0 results for: {query}_")
        compiled_md.append("")
        compiled_md.append(f"_Search URL: {search_url}_")
        compiled_md.append("")
        compiled_md.append("_Next step: retry with browser-visible research._")
        compiled_md.append("")
    elif not curated_pages:
        compiled_md.append("_No pages could be scraped. Showing search snippets instead._")
        compiled_md.append("")
        for i, r in enumerate(search_results, 1):
            compiled_md.append(f"## {i}. {r['title']}")
            compiled_md.append(f"")
            compiled_md.append(f"**URL:** {r['url']}")
            compiled_md.append(f"")
            compiled_md.append(r["snippet"])
            compiled_md.append("")
    else:
        prompt_family = get_prompt_family()
        try:
            synthesis_prompt = prompt_family.summarize_prompt(query, curated_pages)
        except Exception:
            synthesis_prompt = None

        for idx, page in enumerate(curated_pages, 1):
            compiled_md.append(f"## Source {idx}: {page['title']}")
            compiled_md.append(f"")
            compiled_md.append(f"**URL:** {page['url']}")
            compiled_md.append(f"")
            if page["assets"]:
                compiled_md.append(f"**Assets downloaded:** {len(page['assets'])}")
                for asset in page["assets"]:
                    compiled_md.append(f"- `{asset['relative_path']}`")
                compiled_md.append("")
            compiled_md.append(page["markdown"])
            compiled_md.append("")
            compiled_md.append("---")
            compiled_md.append("")

        if synthesis_prompt:
            compiled_md.append("## Synthesis")
            compiled_md.append("")
            compiled_md.append("*[Synthesis requires an LLM call; raw sources are included above.]*")
            compiled_md.append("")

    report_text = "\n".join(compiled_md)

    if resolved_save and os.path.isdir(resolved_save):
        filepath = os.path.join(resolved_save, f"{session_name}_compiled_research.md")
    elif resolved_save:
        filepath = resolved_save
    else:
        filepath = os.path.join(session_dir, "compiled_research.md")

    os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(report_text)

    log_action("research_topic", {"topic": topic, "max_results": max_results, "save_path": save_path}, "approved", f"Report saved to {filepath}")

    docx_path = _convert_to_docx(filepath)
    if docx_path:
        log_action("research_topic", {"topic": topic, "max_results": max_results, "save_path": save_path}, "approved", f"Word document saved to {docx_path}")

    summary = (
        f"Research complete. Report saved to {filepath}\n"
        f"Sources scraped: {len(pages)}/{len(search_results)} results\n"
        f"Sources after curation: {len(curated_pages)}\n\n"
    )
    if docx_path:
        summary += f"Word document saved to {docx_path}\n\n"
    summary += report_text[:4000]
    if len(report_text) > 4000:
        summary += "\n\n...[truncated]..."
    return summary


def _open_in_browser(url: str) -> None:
    try:
        import webbrowser
        webbrowser.open(url)
    except Exception:
        pass


def research_topic(topic: str, max_results: int = 5, save_path: str = "") -> str:
    query = topic.strip()
    if not query:
        return "[error] Empty research topic"

    cleanup_phrases = [
        "give results in download",
        "save to downloads",
        "save to download",
        "and save to",
        "and give results",
        "in download",
        "to download",
    ]
    lowered = query.lower()
    for phrase in cleanup_phrases:
        if phrase in lowered:
            query = query[:lowered.index(phrase)].strip()
            lowered = query.lower()

    worker_response = _try_worker_research(query, max_results, save_path)
    if worker_response and worker_response.get("status") == "success":
        return worker_response.get("summary", "Research complete via worker.")
    if worker_response and worker_response.get("status") == "failed":
        return f"[research_worker] Worker failed: {worker_response.get('error')}"

    inline_result = _run_research_inline(topic, max_results, save_path)

    failure_markers = ("_SEARCH_FAILED_", "_No pages could be scraped", "_No search results found")
    if not any(marker in inline_result for marker in failure_markers):
        return inline_result

    try:
        import importlib
        tavily_module = importlib.import_module("agents.Research tools")
        return tavily_module.research_topic(
            query,
            max_results=max_results,
            save_path=save_path or None,
        )
    except Exception as e:
        return f"{inline_result}\n[fallback] Tavily research also failed: {e}"


def list_reports() -> str:
    _ensure_reports_dir()
    files = sorted(os.listdir(REPORTS_DIR))
    if not files:
        return "No research reports found."
    return "\n".join(files)
