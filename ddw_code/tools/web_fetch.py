"""`web_fetch` — fetch a URL and return a plain-text approximation of the body."""
from __future__ import annotations

import re
from typing import Any

import httpx

_MAX_CHARS_DEFAULT = 10_000
_MAX_BYTES = 2_000_000  # 2 MB hard cap
_TAG_RX = re.compile(r"<[^>]+>")
_SCRIPT_RX = re.compile(r"<script\b[^>]*>.*?</script>", re.IGNORECASE | re.DOTALL)
_STYLE_RX = re.compile(r"<style\b[^>]*>.*?</style>", re.IGNORECASE | re.DOTALL)
_BLANK_RX = re.compile(r"\n{3,}")
_WS_RX = re.compile(r"[ \t]+")


def _html_to_text(html: str) -> str:
    """Best-effort HTML → plain text. Strips scripts/styles and tags.

    For serious extraction users should reach for `web_extract`; this is the
    low-cost fallback when only the rendered text is needed.
    """
    text = _SCRIPT_RX.sub(" ", html)
    text = _STYLE_RX.sub(" ", text)
    text = _TAG_RX.sub(" ", text)
    # Common entity replacements (minimal set).
    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
    )
    text = _WS_RX.sub(" ", text)
    text = _BLANK_RX.sub("\n\n", text)
    return text.strip()


async def web_fetch(
    url: str,
    max_chars: int = _MAX_CHARS_DEFAULT,
    timeout: float = 20.0,
) -> str:
    """Fetch `url` and return its body as plain text (capped at `max_chars`).

    Args:
        url: HTTP(S) URL to fetch.
        max_chars: Cap on the returned string length.
        timeout: Network timeout in seconds.

    Returns:
        Plain-text body, or a `web_fetch error:` message on failure.
    """
    if not url or not url.startswith(("http://", "https://")):
        return "web_fetch error: url must start with http:// or https://"
    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "ddw-code-cli/0.1 (+web_fetch)"},
        ) as client:
            resp = await client.get(url)
    except httpx.HTTPError as e:
        return f"web_fetch error: {e}"
    if resp.status_code >= 400:
        return f"web_fetch error: HTTP {resp.status_code} for {url}"
    raw = resp.content[:_MAX_BYTES]
    # Try to decode as utf-8 with fallbacks.
    try:
        text = raw.decode("utf-8", errors="replace")
    except Exception as e:  # pragma: no cover - extremely defensive
        return f"web_fetch error: failed to decode body: {e}"
    content_type = resp.headers.get("content-type", "").lower()
    if "html" in content_type or "<html" in text[:200].lower():
        text = _html_to_text(text)
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n... [truncated at {max_chars} chars]"
    return text


def schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "HTTP(S) URL to fetch.",
            },
            "max_chars": {
                "type": "integer",
                "description": "Maximum characters to return.",
                "default": _MAX_CHARS_DEFAULT,
                "minimum": 100,
            },
            "timeout": {
                "type": "number",
                "description": "Network timeout in seconds.",
                "default": 20.0,
                "minimum": 1.0,
            },
        },
        "required": ["url"],
    }
