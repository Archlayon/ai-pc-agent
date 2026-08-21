"""
Research scraper: extracts readable text from web pages and downloads
all images / media assets locally.

Outputs structured Markdown so the main content remains readable text,
while images are saved to a local assets folder and referenced from
the Markdown.
"""
from __future__ import annotations

import os
import re
import hashlib
import mimetypes
import asyncio
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup, Tag

from utils.workers import WorkerPool

REQUEST_TIMEOUT = 8
MAX_ASSET_BYTES = 8 * 1024 * 1024  # 8 MB per asset cap
_worker_pool = WorkerPool(max_workers=4, rate_limit_delay=1.0)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
}

UNWANTED_TAGS = {
    "script", "style", "noscript", "nav", "footer", "header",
    "aside", "form", "iframe", "svg", "canvas", "button",
    "input", "select", "textarea", "meta", "link",
}


def _safe_request(url: str) -> requests.Response | None:
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
    for node in soup.find_all(True):
        if node is None:
            continue
        attrs = getattr(node, "attrs", None)
        if attrs and attrs.get("aria-hidden") == "true":
            node.decompose()


def _guess_extension(url: str, content_type: str | None) -> str:
    ext = mimetypes.guess_extension(content_type.split(";")[0].strip()) if content_type else None
    if ext:
        return ext
    path = urlparse(url).path
    if "." in path:
        ext = "." + path.rsplit(".", 1)[-1].split("?")[0].lower()
        if ext in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp", ".ico"}:
            return ext
    return ".bin"


def _asset_filename(url: str, content_type: str | None) -> str:
    ext = _guess_extension(url, content_type)
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]
    return f"{digest}{ext}"


def download_assets(soup: BeautifulSoup, base_url: str, assets_dir: Path) -> list[dict]:
    assets_dir.mkdir(parents=True, exist_ok=True)
    downloaded: list[dict] = []

    img_tags = soup.find_all("img")
    svg_tags = soup.find_all("svg")

    seen_urls: set[str] = set()

    for tag in img_tags + svg_tags:
        if tag.name == "img":
            raw_src = tag.get("src") or tag.get("data-src") or tag.get("data-srcset")
            if not raw_src:
                continue
            if tag.name == "img" and "data-srcset" in tag.attrs and "src" not in tag.attrs:
                raw_src = raw_src.split(",")[0].strip().split(" ")[0].strip()
        else:
            raw_src = None

        if not raw_src:
            continue

        abs_url = urljoin(base_url, raw_src)
        if abs_url in seen_urls:
            continue
        seen_urls.add(abs_url)

        filename = _asset_filename(abs_url, None)
        dest = assets_dir / filename

        if not dest.exists():
            resp = _safe_request(abs_url)
            if resp and len(resp.content) <= MAX_ASSET_BYTES:
                dest.write_bytes(resp.content)

        if dest.exists():
            rel_path = f"assets/{dest.name}"
            if tag.name == "img":
                tag["src"] = rel_path
                tag["data-local"] = "true"
            downloaded.append({
                "original_url": abs_url,
                "local_path": str(dest),
                "relative_path": rel_path,
            })

    return downloaded


def _tag_to_markdown(tag: Tag, base_soup: BeautifulSoup) -> str:
    if isinstance(tag, str):
        return tag

    if not hasattr(tag, "name") or tag.name is None:
        return ""

    name = tag.name.lower()

    if name in {"br", "hr"}:
        return "\n"

    if name == "p":
        return "".join(_tag_to_markdown(c, base_soup) for c in tag.children).strip() + "\n\n"

    if name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
        level = int(name[1])
        text = "".join(_tag_to_markdown(c, base_soup) for c in tag.children).strip()
        return f"{'#' * level} {text}\n\n"

    if name in {"ul", "ol"}:
        items = []
        for i, li in enumerate(tag.find_all("li", recursive=False), 1):
            bullet = f"{i}." if name == "ol" else "-"
            text = "".join(_tag_to_markdown(c, base_soup) for c in li.children).strip()
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
                "".join(_tag_to_markdown(c, base_soup) for c in col.children).strip().replace("|", "/")
                for col in cols
            ))
        if not table_rows:
            return ""
        return "\n".join(table_rows) + "\n\n"

    if name == "a":
        href = tag.get("href", "")
        text = "".join(_tag_to_markdown(c, base_soup) for c in tag.children).strip()
        if text:
            return f"[{text}]({href})"
        return ""

    if name in {"b", "strong"}:
        text = "".join(_tag_to_markdown(c, base_soup) for c in tag.children)
        return f"**{text}**"

    if name in {"i", "em"}:
        text = "".join(_tag_to_markdown(c, base_soup) for c in tag.children)
        return f"*{text}*"

    if name in {"code", "pre"}:
        text = "".join(_tag_to_markdown(c, base_soup) for c in tag.children)
        return f"`{text}`"

    if name == "blockquote":
        text = "".join(_tag_to_markdown(c, base_soup) for c in tag.children).strip()
        return "\n".join(f"> {line}" for line in text.split("\n")) + "\n\n"

    if name == "div" or name == "span":
        return "".join(_tag_to_markdown(c, base_soup) for c in tag.children)

    return "".join(_tag_to_markdown(c, base_soup) for c in tag.children)


def soup_to_markdown(soup: BeautifulSoup) -> str:
    body = soup.find("body") or soup
    parts: list[str] = []
    for child in body.children:
        if isinstance(child, str):
            text = child.strip()
            if text:
                parts.append(text)
        elif hasattr(child, "name") and child.name:
            md = _tag_to_markdown(child, soup)
            if md:
                parts.append(md)
    text = "\n".join(parts)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def scrape_page(url: str, assets_root: Path, visited_urls: set[str] | None = None) -> dict | None:
    if visited_urls is not None and url in visited_urls:
        return None

    page = _scrape_with_crawl4ai(url, assets_root)
    if page:
        if visited_urls is not None:
            visited_urls.add(url)
        return page

    resp = _safe_request(url)
    if resp is None:
        if visited_urls is not None:
            visited_urls.add(url)
        return None

    html = resp.text
    soup = BeautifulSoup(html, "lxml")

    title = ""
    title_tag = soup.find("title")
    if title_tag:
        title = title_tag.get_text(strip=True)

    _clean_soup(soup)

    assets_dir = assets_root / "assets"
    downloaded = download_assets(soup, url, assets_dir)

    markdown = soup_to_markdown(soup)

    if visited_urls is not None:
        visited_urls.add(url)

    return {
        "title": title,
        "url": url,
        "markdown": markdown,
        "assets": downloaded,
    }


def _scrape_with_crawl4ai(url: str, assets_root: Path) -> dict | None:
    try:
        from crawl4ai import AsyncWebCrawler
        from crawl4ai.async_configs import BrowserConfig, CrawlerRunConfig
    except ImportError:
        return None

    async def _crawl() -> dict | None:
        browser_cfg = BrowserConfig(
            headless=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )
            },
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
                    if first_line.startswith("# "):
                        title = first_line[2:].strip()
                    else:
                        title = first_line[:120]

                return {
                    "title": title,
                    "url": url,
                    "markdown": markdown,
                    "assets": [],
                }
        except Exception:
            return None

    try:
        return asyncio.run(_crawl())
    except Exception:
        return None


def _search_web(query: str, max_results: int = 5) -> list[dict]:
    results = [
        _search_duckduckgo_html(query, max_results),
        _search_duckduckgo_lite(query, max_results),
        _search_duckduckgo_api(query, max_results),
        _search_wikipedia(query, max_results),
        _search_google(query, max_results),
    ]
    merged: list[dict] = []
    seen: set[str] = set()
    for result in results:
        if not result:
            continue
        for item in result:
            url = item.get("href") or item.get("url") or ""
            if url and url in seen:
                continue
            if url:
                seen.add(url)
            merged.append(item)
            if len(merged) >= max_results:
                return merged
    return merged[:max_results]


def _search_duckduckgo_html(query: str, max_results: int) -> list[dict]:
    results: list[dict] = []
    try:
        url = "https://html.duckduckgo.com/html/"
        params = {"q": query}
        headers = {"User-Agent": HEADERS["User-Agent"]}
        resp = requests.post(url, data=params, headers=headers, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        html = resp.text
        soup = BeautifulSoup(html, "lxml")

        seen_urls: set[str] = set()
        for result_div in soup.select(".result")[:max_results]:
            title_tag = result_div.select_one(".result__a") or result_div.select_one("a")
            snippet_tag = result_div.select_one(".result__body")
            title = title_tag.get_text(strip=True) if title_tag else ""
            snippet = snippet_tag.get_text(strip=True) if snippet_tag else ""
            href = title_tag.get("href", "") if title_tag else ""
            if href and href.startswith("//"):
                href = "https:" + href
            if href and "duckduckgo" not in href and href not in seen_urls:
                seen_urls.add(href)
                results.append({"title": title, "url": href, "snippet": snippet})

        if not results:
            for m in re.finditer(r'href="(https?://[^"]+)"', html):
                href = m.group(1)
                if "duckduckgo" in href or href in seen_urls:
                    continue
                seen_urls.add(href)
                results.append({"title": "", "url": href, "snippet": ""})
    except Exception:
        pass
    return results


def _search_duckduckgo_lite(query: str, max_results: int) -> list[dict]:
    results: list[dict] = []
    try:
        url = "https://lite.duckduckgo.com/lite/"
        params = {"q": query}
        headers = {"User-Agent": HEADERS["User-Agent"]}
        resp = requests.post(url, data=params, headers=headers, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        html = resp.text
        soup = BeautifulSoup(html, "lxml")

        seen_urls: set[str] = set()
        for row in soup.select(".result-table tbody tr")[:max_results]:
            title_a = row.select_one(".result-link a") or row.select_one("a")
            snippet_td = row.select_one(".result-snippet") or row.select_one("td")
            if title_a:
                title = title_a.get_text(strip=True)
                href = title_a.get("href", "")
                snippet = snippet_td.get_text(strip=True) if snippet_td else ""
                if href and href.startswith("//"):
                    href = "https:" + href
                if href and "duckduckgo" not in href and href not in seen_urls:
                    seen_urls.add(href)
                    results.append({"title": title, "url": href, "snippet": snippet})
    except Exception:
        pass
    return results


def _search_duckduckgo_api(query: str, max_results: int) -> list[dict]:
    results: list[dict] = []
    try:
        url = f"https://api.duckduckgo.com/?q={requests.utils.quote(query)}&format=json&no_html=1"
        headers = {"User-Agent": HEADERS["User-Agent"]}
        resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        seen_urls: set[str] = set()
        for item in data.get("RelatedTopics", [])[:max_results]:
            if isinstance(item, dict) and "Text" in item:
                href = item.get("FirstURL", "")
                if href and "duckduckgo" not in href and href not in seen_urls:
                    seen_urls.add(href)
                    results.append({
                        "title": item.get("Text", ""),
                        "url": href,
                        "snippet": item.get("Text", ""),
                    })
    except Exception:
        pass
    return results


def _search_wikipedia(query: str, max_results: int) -> list[dict]:
    results: list[dict] = []
    try:
        url = f"https://en.wikipedia.org/w/api.php?action=opensearch&search={requests.utils.quote(query)}&limit=5&format=json"
        headers = {"User-Agent": HEADERS["User-Agent"]}
        resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        titles = data[1] if len(data) > 1 else []
        urls = data[3] if len(data) > 3 else []
        seen_urls: set[str] = set()
        for i, title in enumerate(titles[:max_results]):
            href = urls[i] if i < len(urls) else ""
            if href and href not in seen_urls:
                seen_urls.add(href)
                results.append({"title": title, "url": href, "snippet": f"Wikipedia: {title}"})
    except Exception:
        pass
    return results


def _search_google(query: str, max_results: int) -> list[dict]:
    results: list[dict] = []
    try:
        url = f"https://www.google.com/search?q={requests.utils.quote(query)}&num={max_results}"
        headers = {"User-Agent": HEADERS["User-Agent"]}
        resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        html = resp.text
        soup = BeautifulSoup(html, "lxml")

        seen_urls: set[str] = set()
        for g in soup.select("div.g")[:max_results]:
            a_tag = g.select_one("a")
            if not a_tag:
                continue
            href = a_tag.get("href", "")
            if not href.startswith("http"):
                continue
            title = a_tag.get_text(strip=True)
            snippet_tag = g.select_one("div.VwiC3b") or g.select_one("span.st") or g.select_one("div[data-sncf]")
            snippet = snippet_tag.get_text(strip=True) if snippet_tag else ""
            if href not in seen_urls:
                seen_urls.add(href)
                results.append({"title": title, "url": href, "snippet": snippet})
    except Exception:
        pass
    return results


def normalize_search_results(raw: list[dict]) -> list[dict]:
    """Normalize retriever output to a common schema.

    Maps various key names to ``href``, ``body``, ``title`` so downstream
    code doesn't need to know which retriever produced the data.
    """
    normalized: list[dict] = []
    for item in raw:
        href = item.get("href") or item.get("url") or ""
        body = item.get("body") or item.get("content") or item.get("snippet") or ""
        title = item.get("title") or href
        normalized.append(
            {
                "title": title,
                "href": href,
                "body": body,
                "url": href,
                "content": body,
                "snippet": body[:200],
            }
        )
    return normalized


def curate_sources(
    query: str,
    sources: list[dict],
    llm_callable=None,
    min_quality: float = 0.5,
) -> list[dict]:
    """Filter sources down to high-quality, relevant ones.

    If *llm_callable* is provided (a callable taking a prompt string and
    returning a response string), it is used to score sources via the
    curation prompt. Otherwise a simple heuristic based on domain
    reputation is applied.

    Args:
        query: The original research query.
        sources: List of source dicts from retrievers.
        llm_callable: Optional async or sync callable ``prompt -> str``.
        min_quality: Minimum quality threshold in ``[0, 1]``. Sources below
            this are dropped.

    Returns:
        Filtered list of sources, sorted by estimated quality.
    """
    if not sources:
        return []

    if llm_callable is None:
        return _heuristic_curate(sources, min_quality)

    try:
        from prompts import get_prompt_family

        prompt_family = get_prompt_family()
        prompt = prompt_family.curate_sources_prompt(query, sources)
        response = llm_callable(prompt)
        return _parse_curation_response(sources, response, min_quality)
    except Exception:
        return _heuristic_curate(sources, min_quality)


def _heuristic_curate(sources: list[dict], min_quality: float) -> list[dict]:
    """Simple domain-reputation heuristic when no LLM is available."""
    trusted = {
        ".edu": 0.8,
        ".gov": 0.9,
        ".ac.uk": 0.8,
        ".nih.gov": 0.9,
        ".who.int": 0.9,
        ".britannica.com": 0.8,
        ".wikipedia.org": 0.7,
        ".github.com": 0.6,
    }
    scored: list[tuple[float, dict]] = []
    for src in sources:
        url = src.get("href") or src.get("url") or ""
        score = 0.4
        for domain, boost in trusted.items():
            if domain in url.lower():
                score = max(score, boost)
                break
        text = (src.get("body") or src.get("content") or "").strip()
        if len(text) > 300:
            score += 0.1
        if src.get("title"):
            score += 0.05
        score = min(score, 1.0)
        scored.append((score, src))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [src for score, src in scored if score >= min_quality]


def _parse_curation_response(
    original_sources: list[dict],
    response: str,
    min_quality: float,
) -> list[dict]:
    """Parse LLM curation JSON response."""
    import json
    import re

    try:
        match = re.search(r"\[.*\]", response, re.DOTALL)
        if not match:
            return original_sources[: max(3, len(original_sources) // 2)]
        decisions = json.loads(match.group(0))
    except Exception:
        return original_sources[: max(3, len(original_sources) // 2)]

    keep: list[dict] = []
    for decision in decisions:
        idx = decision.get("index") - 1
        if 0 <= idx < len(original_sources):
            relevance = float(decision.get("relevance", 3))
            credibility = float(decision.get("credibility", 3))
            if relevance >= 3 and credibility >= 3:
                keep.append(original_sources[idx])
    if not keep:
        keep = original_sources[: max(3, len(original_sources) // 2)]
    return keep
