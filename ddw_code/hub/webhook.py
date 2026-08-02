"""Webhook delivery.

A small in-process dispatcher that fans out events to registered URLs.
Real deliveries use `httpx.AsyncClient`; tests can substitute a stub.
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

import httpx


@dataclass
class WebhookEndpoint:
    """A single webhook target."""

    url: str
    secret: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    timeout: float = 10.0


@dataclass
class WebhookEvent:
    """An event ready to be delivered to subscribers."""

    event: str
    payload: dict[str, Any] = field(default_factory=dict)
    delivered_at: float | None = None
    status_code: int | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "event": self.event,
            "payload": self.payload,
            "delivered_at": self.delivered_at,
            "status_code": self.status_code,
            "error": self.error,
        }


class WebhookDispatcher:
    """Fire-and-forget webhook delivery with retries."""

    def __init__(self, max_retries: int = 2) -> None:
        self._endpoints: dict[str, list[WebhookEndpoint]] = {}
        self._max_retries = max(1, int(max_retries))
        self._client: httpx.AsyncClient | None = None
        self._transport: Callable[..., Any] | None = None  # for tests

    def subscribe(self, event: str, endpoint: WebhookEndpoint) -> None:
        self._endpoints.setdefault(event, []).append(endpoint)

    def unsubscribe(self, event: str, url: str) -> bool:
        eps = self._endpoints.get(event)
        if not eps:
            return False
        before = len(eps)
        self._endpoints[event] = [e for e in eps if e.url != url]
        return len(self._endpoints[event]) < before

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=10.0)
        return self._client

    def set_transport(self, transport: Callable[..., Any]) -> None:
        """Inject a transport (used by tests to avoid real HTTP)."""
        self._transport = transport

    async def dispatch(self, event: str, payload: dict[str, Any]) -> list[WebhookEvent]:
        """Deliver `event` to every subscribed endpoint.

        Returns a list of per-endpoint `WebhookEvent` records.
        """
        endpoints = list(self._endpoints.get(event, []))
        if not endpoints:
            return []
        out: list[WebhookEvent] = []
        for ep in endpoints:
            record = WebhookEvent(event=event, payload=dict(payload))
            body = json.dumps({"event": event, "payload": payload}, ensure_ascii=False)
            headers = {"Content-Type": "application/json", **ep.headers}
            for attempt in range(self._max_retries + 1):
                try:
                    if self._transport is not None:
                        await self._transport(ep.url, body=body, headers=headers)
                    else:
                        client = await self._ensure_client()
                        resp = await client.post(
                            ep.url, content=body, headers=headers, timeout=ep.timeout
                        )
                        record.status_code = resp.status_code
                except Exception as e:
                    record.error = str(e)
                record.delivered_at = time.time()
                if record.error is None and (record.status_code or 0) < 400:
                    break
                # Back off briefly before retrying.
                await asyncio.sleep(0.05 * (attempt + 1))
            out.append(record)
        return out


__all__ = [
    "WebhookDispatcher",
    "WebhookEndpoint",
    "WebhookEvent",
]
