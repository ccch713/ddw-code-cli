"""SSE / HTTP transport for MCP.

A real MCP HTTP+SSE implementation streams newline-delimited JSON
events from `GET <url>`. For the CLI's needs we provide just enough to
make the client testable: a single shared session that can `POST`
requests and read responses from a backing asyncio queue.

If you have a live MCP server, point this at it. For local development
you can spin up a minimal server and exercise the client against it.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx


class SseTransport:
    """An MCP HTTP+SSE transport using `httpx`."""

    def __init__(
        self,
        url: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        if not url:
            raise ValueError("url must be non-empty")
        self.url = url
        self.headers = dict(headers or {})
        self._client: httpx.AsyncClient | None = None
        self._incoming: asyncio.Queue[str] | None = None
        self._reader_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0),
            headers={"Accept": "text/event-stream", **self.headers},
        )
        # Open the SSE stream in the background.
        self._incoming = asyncio.Queue()
        self._reader_task = asyncio.create_task(self._drain_sse())

    async def close(self) -> None:
        if self._reader_task is not None:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except (asyncio.CancelledError, Exception):
                pass
            self._reader_task = None
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        self._incoming = None

    async def _drain_sse(self) -> None:
        """Read the SSE stream and push events into the local queue."""
        if self._client is None:
            return
        try:
            async with self._client.stream("GET", self.url) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    payload = line[len("data:"):].strip()
                    if not payload or payload == "[DONE]":
                        continue
                    if self._incoming is not None:
                        await self._incoming.put(payload)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Reader died — close will clean up.
            return

    async def send(self, payload: str) -> None:
        if self._client is None:
            raise RuntimeError("transport not started")
        # Standard MCP-over-HTTP posts to the same URL.
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"invalid JSON-RPC payload: {e}") from e
        resp = await self._client.post(self.url, json=data, headers=self.headers)
        resp.raise_for_status()
        if resp.headers.get("content-type", "").startswith("application/json"):
            text = resp.text
            if self._incoming is not None:
                await self._incoming.put(text)

    async def recv(self) -> str | None:
        if self._incoming is None:
            raise RuntimeError("transport not started")
        return await self._incoming.get()


__all__ = ["SseTransport"]
