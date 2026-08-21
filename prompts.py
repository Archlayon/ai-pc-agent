"""
Prompt family for the research pipeline.

Provides structured prompts for the key LLM calls in the research flow:
- planning sub-queries
- summarizing scraped pages into a coherent report
- curating sources by relevance/credibility

All prompts are plain strings so they work with any LLM provider.
"""
from __future__ import annotations


class PromptFamily:
    """Base prompt family. Subclass or replace for model-specific tweaks."""

    @staticmethod
    def plan_research_prompt(query: str, search_results: list[dict]) -> str:
        """Prompt the LLM to generate sub-queries from initial search results."""
        context = "\n".join(
            f"- {r.get('title', '')}: {r.get('body') or r.get('content', '')[:200]}"
            for r in search_results[:5]
        )
        return (
            "You are a research planning assistant.\n"
            f"Given the topic: {query}\n\n"
            "Here are some initial search results:\n"
            f"{context}\n\n"
            "Generate 3-5 specific sub-queries that would help produce a "
            "comprehensive, factual research report. Return only the queries, "
            "one per line, no numbering."
        )

    @staticmethod
    def summarize_prompt(query: str, pages: list[dict]) -> str:
        """Prompt the LLM to synthesize scraped pages into a report section."""
        docs = []
        for i, page in enumerate(pages, 1):
            title = page.get("title", f"Source {i}")
            text = page.get("markdown") or page.get("text") or page.get("body", "")
            docs.append(f"## {title}\n{text[:3000]}")
        context = "\n\n".join(docs)
        return (
            "You are a research report writer. Produce a clear, well-structured "
            "Markdown report on the following topic, using ONLY the provided "
            "sources. Cite sources as [N] where N is the source number.\n\n"
            f"# Topic\n{query}\n\n"
            f"# Sources\n{context}\n\n"
            "Write a comprehensive report with headings and bullet points. "
            "Do not add information not present in the sources."
        )

    @staticmethod
    def curate_sources_prompt(query: str, sources: list[dict]) -> str:
        """Prompt the LLM to score sources and keep only high-quality ones."""
        items = []
        for i, s in enumerate(sources, 1):
            title = s.get("title", "")
            url = s.get("href") or s.get("url", "")
            body = s.get("body") or s.get("content", "")[:300]
            items.append(f"[{i}] {title}\nURL: {url}\nSnippet: {body}")
        context = "\n\n".join(items[:10])
        return (
            "You are a source quality evaluator. Score each of the following "
            f"sources for the query: {query}\n\n"
            f"{context}\n\n"
            "For each source, return a JSON array of objects with keys:\n"
            '  "index" (int, matching the [N] above),\n'
            '  "relevance" (1-5),\n'
            '  "credibility" (1-5),\n'
            '  "keep" (true/false).\n'
            "Keep a source only if relevance >= 3 AND credibility >= 3.\n"
            "Return ONLY valid JSON, no other text."
        )


def get_prompt_family(name: str = "default") -> PromptFamily:
    """Return a prompt family by name.

    Args:
        name: Prompt family name. Currently only ``"default"`` is supported.

    Returns:
        A :class:`PromptFamily` instance.
    """
    return PromptFamily()
