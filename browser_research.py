"""
Browser-based research agent.

Opens a visible Chromium browser, performs Google searches, visits each
result one at a time (closing the previous tab), scrapes page content,
and compiles a cited Markdown report.

No search API keys needed — it uses the browser just like a human.
Requires:
    pip install crawl4ai
    playwright install chromium
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import re
import sys
from pathlib import Path
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

REPORTS_DIR = os.path.expanduser("~/.local/share/ai-pc-agent/reports")
REQUEST_TIMEOUT = 15
MAX_ASSET_BYTES = 8 * 1024 * 1024

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}

UNWANTED_TAGS = {
    "script", "style", "noscript", "nav", "footer", "header",
    "aside", "form", "iframe", "svg", "canvas", "button",
    "input", "select", "textarea", "meta", "link",
}


def _safe_request(url: str):
    import requests
    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp
    except Exception:
        return None


def _clean_soup(soup: BeautifulSoup) -> None:
    for tag in UNWANTED_TAGS:
        for node in soup.find_all(tag):
            node.decompose()


def _download_assets(soup: BeautifulSoup, base_url: str, assets_dir: Path) -> list[dict]:
    assets_dir.mkdir(parents=True, exist_ok=True)
    downloaded: list[dict] = []
    seen_urls: set[str] = set()

    for tag in soup.find_all("img"):
        raw_src = tag.get("src") or tag.get("data-src") or tag.get("data-srcset")
        if not raw_src:
            continue
        if "data-srcset" in tag.attrs and "src" not in tag.attrs:
            raw_src = raw_src.split(",")[0].strip().split(" ")[0].strip()

        abs_url = urljoin(base_url, raw_src)
        if abs_url in seen_urls:
            continue
        seen_urls.add(abs_url)

        ext = os.path.splitext(urlparse(abs_url).path)[1].lower()
        if ext not in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp", ".ico"}:
            ext = ".bin"
        filename = f"{hashlib.sha256(abs_url.encode()).hexdigest()[:12]}{ext}"
        dest = assets_dir / filename

        if not dest.exists():
            resp = _safe_request(abs_url)
            if resp and len(resp.content) <= MAX_ASSET_BYTES:
                dest.write_bytes(resp.content)

        if dest.exists():
            rel_path = f"assets/{dest.name}"
            tag["src"] = rel_path
            downloaded.append({"original_url": abs_url, "local_path": str(dest), "relative_path": rel_path})

    return downloaded


def _tag_to_markdown(tag) -> str:
    if isinstance(tag, str):
        return tag
    if not hasattr(tag, "name") or tag.name is None:
        return ""

    name = tag.name.lower()
    if name in {"br", "hr"}:
        return "\n"
    if name == "p":
        return "".join(_tag_to_markdown(c) for c in tag.children).strip() + "\n\n"
    if name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
        level = int(name[1])
        text = "".join(_tag_to_markdown(c) for c in tag.children).strip()
        return f"{'#' * level} {text}\n\n"
    if name in {"ul", "ol"}:
        items = []
        for i, li in enumerate(tag.find_all("li", recursive=False), 1):
            bullet = f"{i}." if name == "ol" else "-"
            text = "".join(_tag_to_markdown(c) for c in li.children).strip()
            items.append(f"{bullet} {text}")
        return "\n".join(items) + "\n\n"
    if name == "table":
        rows = tag.find_all("tr")
        if not rows:
            return ""
        table_rows = []
        for row in rows:
            cols = row.find_all(["td", "th"])
            table_rows.append(" | ".join(
                "".join(_tag_to_markdown(c) for c in col.children).strip().replace("|", "/")
                for col in cols
            ))
        return "\n".join(table_rows) + "\n\n"
    if name == "a":
        href = tag.get("href", "")
        text = "".join(_tag_to_markdown(c) for c in tag.children).strip()
        return f"[{text}]({href})" if text else ""
    if name in {"b", "strong"}:
        text = "".join(_tag_to_markdown(c) for c in tag.children)
        return f"**{text}**"
    if name in {"i", "em"}:
        text = "".join(_tag_to_markdown(c) for c in tag.children)
        return f"*{text}*"
    if name in {"code", "pre"}:
        text = "".join(_tag_to_markdown(c) for c in tag.children)
        return f"`{text}`"
    if name == "blockquote":
        text = "".join(_tag_to_markdown(c) for c in tag.children).strip()
        return "\n".join(f"> {line}" for line in text.split("\n")) + "\n\n"
    if name in {"div", "span"}:
        return "".join(_tag_to_markdown(c) for c in tag.children)
    return "".join(_tag_to_markdown(c) for c in tag.children)


def _soup_to_markdown(soup: BeautifulSoup) -> str:
    body = soup.find("body") or soup
    parts: list[str] = []
    for child in body.children:
        if isinstance(child, str):
            text = child.strip()
            if text:
                parts.append(text)
        elif hasattr(child, "name") and child.name:
            md = _tag_to_markdown(child)
            if md:
                parts.append(md)
    text = "\n".join(parts)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _scrape_html(url: str, assets_root: Path) -> dict | None:
    resp = _safe_request(url)
    if resp is None:
        return None
    soup = BeautifulSoup(resp.text, "lxml")
    title = ""
    title_tag = soup.find("title")
    if title_tag:
        title = title_tag.get_text(strip=True)
    _clean_soup(soup)
    assets_dir = assets_root / "assets"
    downloaded = _download_assets(soup, url, assets_dir)
    markdown = _soup_to_markdown(soup)
    return {"title": title, "url": url, "markdown": markdown, "assets": downloaded}


async def _scrape_with_crawl4ai(url: str, assets_root: Path) -> dict | None:
    try:
        from crawl4ai import AsyncWebCrawler
        from crawl4ai.async_configs import BrowserConfig, CrawlerRunConfig
    except ImportError:
        return None

    async def _crawl() -> dict | None:
        browser_cfg = BrowserConfig(
            headless=True,
            headers={"User-Agent": HEADERS["User-Agent"]},
            java_script_enabled=True,
        )
        run_cfg = CrawlerRunConfig(
            magic=True,
            remove_overlay_elements=True,
            remove_consent_popups=True,
            simulate_user=True,
            cache_mode=True,
        )
        try:
            async with AsyncWebCrawler(config=browser_cfg) as crawler:
                result = await crawler.arun(url=url, config=run_cfg)
                if not result.success:
                    return None
                markdown = result.markdown or ""
                title = ""
                if markdown:
                    first_line = markdown.splitlines()[0].strip()
                    title = first_line[2:].strip() if first_line.startswith("# ") else first_line[:120]
                return {"title": title, "url": url, "markdown": markdown, "assets": []}
        except Exception:
            return None

    try:
        return await _crawl()
    except Exception:
        return None


async def _browser_search_google(query: str, max_results: int = 5) -> list[dict]:
    """Use Playwright to search Google and extract result URLs + snippets."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return []

    results: list[dict] = []
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(user_agent=HEADERS["User-Agent"])
            await page.goto(f"https://www.google.com/search?q={query}&num={max_results}", timeout=30000)
            await page.wait_for_timeout(2000)

            # Try multiple selectors for Google results
            items = await page.query_selector_all("div.g")
            if not items:
                items = await page.query_selector_all("div[data-sncf]")

            for item in items[:max_results]:
                a_tag = await item.query_selector("a")
                if not a_tag:
                    continue
                href = await a_tag.get_attribute("href") or ""
                if not href.startswith("http"):
                    continue
                title = (await a_tag.inner_text()).strip()

                snippet_tag = await item.query_selector("div.VwiC3b") or await item.query_selector("span.st") or await item.query_selector("div[data-sncf]")
                snippet = (await snippet_tag.inner_text()).strip() if snippet_tag else ""

                results.append({"title": title, "url": href, "snippet": snippet})

            await browser.close()
    except Exception:
        pass
    return results


async def _browser_scrape_visible(url: str, assets_root: Path) -> dict | None:
    """Scrape a URL using a visible browser so you can watch if needed."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return None

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)
            context = await browser.new_context(user_agent=HEADERS["User-Agent"])
            page = await context.new_page()
            await page.goto(url, timeout=60000, wait_until="domcontentloaded")
            await page.wait_for_timeout(2000)

            html = await page.content()
            title = await page.title()
            await browser.close()

            soup = BeautifulSoup(html, "lxml")
            _clean_soup(soup)
            assets_dir = assets_root / "assets"
            downloaded = _download_assets(soup, url, assets_dir)
            markdown = _soup_to_markdown(soup)
            return {"title": title, "url": url, "markdown": markdown, "assets": downloaded}
    except Exception:
        return None


def research_topic_browser(
    topic: str,
    max_results: int = 5,
    save_path: str = "",
    headless: bool = True,
) -> str:
    """Research a topic using a real browser, compile a cited Markdown report."""
    query = topic.strip()
    if not query:
        return "[error] Empty research topic"

    session_name = f"{query.replace(' ', '_').replace('/', '_')}"
    session_dir = os.path.join(REPORTS_DIR, f"{session_name}_browser_{__import__('datetime').datetime.now(__import__('datetime').timezone.utc).strftime('%Y%m%d_%H%M%S')}")
    os.makedirs(session_dir, exist_ok=True)

    resolved_save = _resolve_save_path(save_path)
    if resolved_save and os.path.isdir(resolved_save):
        output_dir = resolved_save
    else:
        output_dir = session_dir

    assets_dir = os.path.join(output_dir, "assets")
    os.makedirs(assets_dir, exist_ok=True)

    compiled_md: list[str] = [
        f"# Research Report: {query}",
        "",
        f"**Generated:** {__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()}",
        "",
        "---",
        "",
    ]

    async def _run() -> str:
        search_results = await _browser_search_google(query, max_results=max_results)
        if not search_results:
            compiled_md.append("_Browser search returned no results. Try a different query._")
            compiled_md.append("")
            return "\n".join(compiled_md)

        pages: list[dict] = []
        for i, r in enumerate(search_results):
            url = r.get("url", "")
            if not url:
                continue
            compiled_md.append(f"## [{i+1}] {r.get('title', url)}")
            compiled_md.append(f"")
            compiled_md.append(f"**URL:** {url}")
            compiled_md.append(f"")
            compiled_md.append(f"> {r.get('snippet', '')}")
            compiled_md.append("")

            print(f"[research] Scraping {url} ...", flush=True)
            page_data = await _browser_scrape_visible(url, Path(output_dir))
            if page_data:
                pages.append(page_data)
                compiled_md.append(page_data["markdown"])
                compiled_md.append("")
                compiled_md.append("---")
                compiled_md.append("")
            else:
                compiled_md.append(f"_[Could not scrape this page]_")
                compiled_md.append("")
                compiled_md.append("---")
                compiled_md.append("")

        if not pages:
            compiled_md.append("_No pages could be scraped._")
            compiled_md.append("")

        return "\n".join(compiled_md)

    report_text = asyncio.run(_run())

    if resolved_save and os.path.isdir(resolved_save):
        filepath = os.path.join(resolved_save, f"{session_name}_compiled_research.md")
    elif resolved_save:
        filepath = resolved_save
    else:
        filepath = os.path.join(session_dir, "compiled_research.md")

    os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(report_text)

    from audit_log import log_action
    log_action("research_topic_browser", {"topic": topic, "max_results": max_results, "save_path": save_path}, "approved", f"Report saved to {filepath}")

    summary = (
        f"Browser research complete. Report saved to {filepath}\n"
        f"Sources attempted: {max_results}\n\n"
        f"{report_text[:4000]}"
    )
    if len(report_text) > 4000:
        summary += "\n\n...[truncated]..."
    return summary


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


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Browser-based research agent")
    parser.add_argument("topic", help="Research topic")
    parser.add_argument("--max-results", type=int, default=5, help="Max pages to scrape")
    parser.add_argument("--save-path", default="", help="Output folder or file path")
    parser.add_argument("--visible", action="store_true", help="Show browser window")
    args = parser.parse_args()

    result = research_topic_browser(
        args.topic,
        max_results=args.max_results,
        save_path=args.save_path,
        headless=not args.visible,
    )
    print(result)
