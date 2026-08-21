---
name: research_workflow
description: Internet research pipeline — search, scrape, curate sources, write reports
tags: [research, read-only]
risk: low
origin: ai-pc-agent
---

# Research Workflow Skill

## When to Activate

- User asks to "research", "study", "investigate" a topic
- User asks to "find information about" or "tell me about" something
- User asks to "scrape" a URL
- User asks to "search Google" for something informational

## Core Concepts

### Three-Stage Pipeline

1. **Search** — query Google/DuckDuckGo, collect top 5 results
2. **Scrape** — visit each result, extract title + markdown content
3. **Synthesize** — LLM writes a Markdown report citing sources as [N]

### Keyword Detection

Research keywords: `research`, `study`, `investigate`, `learn about`,
`explain`, `what is`, `how does`, `tell me about`

Informational search keywords: `information`, `info`, `about`, `how`, `what`,
`why` — if query length > 3 words AND contains an info keyword → research.

### Source Curation

Score each source on:
- **Relevance (1-5):** How directly does it address the query?
- **Credibility (1-5):** Is it from a reputable domain (.edu, .gov, established publication)?

Keep only sources where relevance >= 3 AND credibility >= 3.

### Browser Research Mode

If background search is blocked or user wants visible activity:
- Use `research_topic_browser` which opens a real browser
- Set `headless=False` to watch the browser work
- Scrapes full page content, not just snippets

## Code Examples

```python
# Basic research
research_topic("quantum computing", max_results=5, save_path="~/Documents")

# Browser-visible research
research_topic_browser("machine learning trends", headless=False)
```

## Best Practices

- Save reports to user-specified path if given, otherwise use a default location
- Strip tracking parameters from URLs before scraping
- Handle rate limiting gracefully — retry with backoff
- Include source URLs in all citations
- Don't add information not present in sources
