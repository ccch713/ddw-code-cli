"""`web_search` — best-effort web search via DuckDuckGo HTML (no API key required).

For production use, swap with a real search API (Bing, Brave, Serper, etc.).
This implementation is good enough for a CLI assistant that needs to look
up a few facts in-session.
"""
from __future__ import annotations

import urllib.parse
from typing import Any

import httpx

_DDG_URL = "https://html.duckduckgo.com/html/"
_MAX_RESULTS = 8
_TIMEOUT = 15.0


async def web_search(query: str, max_results: int = 5) -> str:
    """Search the web for `query` and return a snippet list.

    Args:
        query: Search query.
        max_results: Number of results to return (max 8).

    Returns:
        A formatted list of `title — url` lines, or an error string.
    """
    n = max(1, min(int(max_results), _MAX_RESULTS))
    try:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT,
            headers={"User-Agent": "minimax-agent/0.1 (CLI tool)"},
        ) as client:
            resp = await client.post(
                _DDG_URL,
                data={"q": query, "kl": "us-en"},
                follow_redirects=True,
            )
    except httpx.RequestError as e:
        return f"[web_search error: {e}]"
    if resp.status_code != 200:
        return f"[web_search HTTP {resp.status_code}]"
    # Very small parser — DDG HTML uses `<a class="result__a">` and
    # `<a class="result__url">`. We use a few heuristics.
    import re

    html = resp.text
    titles = re.findall(
        r'<a[^>]+class="result__a"[^>]*>(.*?)</a>', html, flags=re.DOTALL
    )
    urls = re.findall(
        r'<a[^>]+class="result__url"[^>]*href="([^"]+)"', html
    )
    snippets = re.findall(
        r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>', html, flags=re.DOTALL
    )
    lines: list[str] = []
    for i in range(min(n, len(titles))):
        title = _strip_tags(titles[i]) if i < len(titles) else "(no title)"
        url = urls[i] if i < len(urls) else ""
        url = urllib.parse.unquote(url) if url else ""
        snippet = _strip_tags(snippets[i]) if i < len(snippets) else ""
        lines.append(f"{i + 1}. {title}\n   {url}\n   {snippet}".rstrip())
    if not lines:
        return "[no results]"
    return "\n\n".join(lines)


def _strip_tags(s: str) -> str:
    import re

    s = re.sub(r"<[^>]+>", "", s)
    return s.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").strip()


def schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query."},
            "max_results": {
                "type": "integer",
                "description": "Number of results (1-8).",
                "default": 5,
                "minimum": 1,
                "maximum": 8,
            },
        },
        "required": ["query"],
    }
