"""
Pluggable retriever system for research scraping.

Each retriever implements a ``search(query, max_results) -> list[dict]``
contract. Results are normalized dicts with at least ``href``/``url`` and
``body``/``content`` keys so downstream scrapers and curators can work
without knowing which retriever produced the data.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Retriever(ABC):
    """Abstract base class for search retrievers."""

    @abstractmethod
    async def search(
        self,
        query: str,
        max_results: int = 5,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Search for results related to *query*.

        Args:
            query: Search query string.
            max_results: Maximum number of results to return.
            **kwargs: Retriever-specific options.

        Returns:
            List of result dicts. Each dict must contain at least one of
            ``href``/``url`` and one of ``body``/``content``/``snippet``.
            Optional keys: ``title``, ``raw_content``, ``image_urls``.
        """
        ...

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}()"


class DuckDuckGoRetriever(Retriever):
    """Search via DuckDuckGo HTML endpoints with multiple fallbacks."""

    async def search(
        self,
        query: str,
        max_results: int = 5,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        from research_scraper import _search_web

        return _search_web(query, max_results=max_results)


class WikipediaRetriever(Retriever):
    """Search Wikipedia via the public OpenSearch API."""

    async def search(
        self,
        query: str,
        max_results: int = 5,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        import requests
        from urllib.parse import quote

        url = (
            "https://en.wikipedia.org/w/api.php"
            f"?action=opensearch&search={quote(query)}&limit={max_results}&format=json"
        )
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )
        }
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            return []

        titles = data[1] if len(data) > 1 else []
        urls = data[3] if len(data) > 3 else []

        results: list[dict[str, Any]] = []
        for i, title in enumerate(titles[:max_results]):
            href = urls[i] if i < len(urls) else ""
            if not href:
                continue
            results.append(
                {
                    "title": title,
                    "href": href,
                    "body": f"Wikipedia: {title}",
                    "content": f"Wikipedia: {title}",
                }
            )
        return results


class GoogleRetriever(Retriever):
    """Search via Google HTML (best-effort, may be rate-limited)."""

    async def search(
        self,
        query: str,
        max_results: int = 5,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        import requests
        from bs4 import BeautifulSoup
        from urllib.parse import quote

        url = f"https://www.google.com/search?q={quote(query)}&num={max_results}"
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )
        }
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")
        except Exception:
            return []

        results: list[dict[str, Any]] = []
        for g in soup.select("div.g")[:max_results]:
            a_tag = g.select_one("a")
            if not a_tag:
                continue
            href = a_tag.get("href", "")
            if not href.startswith("http"):
                continue
            title = a_tag.get_text(strip=True)
            snippet_tag = (
                g.select_one("div.VwiC3b")
                or g.select_one("span.st")
                or g.select_one("div[data-sncf]")
            )
            snippet = snippet_tag.get_text(strip=True) if snippet_tag else ""
            results.append(
                {
                    "title": title,
                    "href": href,
                    "body": snippet,
                    "content": snippet,
                }
            )
        return results


def get_retriever(name: str) -> Retriever:
    """Factory: return a retriever instance by name.

    Args:
        name: Retriever name. Supported: ``duckduckgo``, ``wikipedia``,
            ``google``. Defaults to ``duckduckgo``.

    Returns:
        A :class:`Retriever` instance.
    """
    registry: dict[str, type[Retriever]] = {
        "duckduckgo": DuckDuckGoRetriever,
        "wikipedia": WikipediaRetriever,
        "google": GoogleRetriever,
    }
    cls = registry.get(name.lower(), DuckDuckGoRetriever)
    return cls()
