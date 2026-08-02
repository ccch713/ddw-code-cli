"""`web_extract` — fetch a URL and extract either a CSS-selector match or its title/meta.

This is a deliberately small implementation: a real deployment would replace
it with `trafilatura` or `readability-lxml`. We avoid the hard dependency here
to keep the install footprint tiny, but we follow the same calling shape so
swapping the backend is a one-line change.
"""
from __future__ import annotations

import re
from typing import Any

import httpx

from .web_fetch import _html_to_text

_TITLE_RX = re.compile(r"<title[^>]*>(?P<t>.*?)</title>", re.IGNORECASE | re.DOTALL)
_META_DESC_RX = re.compile(
    r'<meta\s+name=["\']description["\']\s+content=["\'](?P<d>.*?)["\']',
    re.IGNORECASE,
)
_META_DESC_RX2 = re.compile(
    r'<meta\s+content=["\'](?P<d>.*?)["\']\s+name=["\']description["\']',
    re.IGNORECASE,
)


def _extract_title(html: str) -> str:
    m = _TITLE_RX.search(html)
    return m.group("t").strip() if m else ""


def _extract_meta_description(html: str) -> str:
    m = _META_DESC_RX.search(html) or _META_DESC_RX2.search(html)
    return m.group("d").strip() if m else ""


def _extract_selector(html: str, selector: str) -> str:
    """Tiny selector implementation supporting tag and class selectors.

    Supported shapes (all matched case-insensitively for tag names):
    - `tagname`           — every <tagname ...>...</tagname> block
    - `.classname`        — elements whose class attribute contains the token
    - `tagname.classname` — combined

    This is intentionally minimal. Real deployments should pull in
    `selectolax` or `beautifulsoup4`.
    """
    sel = selector.strip()
    if not sel:
        return ""
    if sel.startswith("."):
        cls = sel[1:]
        rx = re.compile(
            rf'<(?P<tag>\w+)[^>]*class=["\'][^"\']*\b{re.escape(cls)}\b[^"\']*["\'][^>]*>(?P<inner>.*?)</\1>',
            re.IGNORECASE | re.DOTALL,
        )
    elif "." in sel:
        tag, cls = sel.split(".", 1)
        rx = re.compile(
            rf'<{re.escape(tag)}[^>]*class=["\'][^"\']*\b{re.escape(cls)}\b[^"\']*["\'][^>]*>(?P<inner>.*?)</{re.escape(tag)}>',
            re.IGNORECASE | re.DOTALL,
        )
    else:
        rx = re.compile(
            rf'<{re.escape(sel)}\b[^>]*>(?P<inner>.*?)</{re.escape(sel)}>',
            re.IGNORECASE | re.DOTALL,
        )
    return "\n\n".join(m.group("inner").strip() for m in rx.finditer(html))


async def web_extract(
    url: str,
    selector: str | None = None,
    timeout: float = 20.0,
    max_chars: int = 10_000,
) -> str:
    """Fetch `url` and return title + meta description (or selector match).

    Args:
        url: HTTP(S) URL.
        selector: Optional CSS-ish selector (`tag`, `.class`, or `tag.class`).
                  If given, only the matching blocks are returned.
        timeout: Network timeout in seconds.
        max_chars: Max characters to return.

    Returns:
        A small structured summary or selector match.
    """
    if not url or not url.startswith(("http://", "https://")):
        return "web_extract error: url must start with http:// or https://"
    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "ddw-code-cli/0.1 (+web_extract)"},
        ) as client:
            resp = await client.get(url)
    except httpx.HTTPError as e:
        return f"web_extract error: {e}"
    if resp.status_code >= 400:
        return f"web_extract error: HTTP {resp.status_code} for {url}"
    html = resp.text
    title = _extract_title(html)
    description = _extract_meta_description(html)
    if selector:
        body = _extract_selector(html, selector)
        if not body:
            return f"web_extract: no match for selector {selector!r} at {url}"
        body = _html_to_text(body)
        if len(body) > max_chars:
            body = body[:max_chars] + f"\n... [truncated at {max_chars} chars]"
        # Selector requests return just the matched content (no metadata header).
        return body
    body = _html_to_text(html)
    if len(body) > max_chars:
        body = body[:max_chars] + f"\n... [truncated at {max_chars} chars]"
    parts: list[str] = [f"url: {url}"]
    if title:
        parts.append(f"title: {title}")
    if description:
        parts.append(f"description: {description}")
    if body:
        parts.append("---")
        parts.append(body)
    return "\n".join(parts).rstrip()


def schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "HTTP(S) URL to fetch.",
            },
            "selector": {
                "type": "string",
                "description": "Optional CSS-ish selector: 'tag', '.class', or 'tag.class'.",
            },
            "timeout": {
                "type": "number",
                "description": "Network timeout in seconds.",
                "default": 20.0,
                "minimum": 1.0,
            },
            "max_chars": {
                "type": "integer",
                "description": "Max characters to return.",
                "default": 10_000,
                "minimum": 100,
            },
        },
        "required": ["url"],
    }
