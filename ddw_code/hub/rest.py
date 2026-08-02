"""Lightweight REST surface for the DDW Code CLI plugin.

A real deployment would mount this with `fastapi` or `starlette`. We
deliberately stay framework-free so the CLI doesn't pull in a web stack
just to expose a couple of endpoints — the same handler functions can
be plugged into FastAPI with one line of glue.

The handlers are designed to be `async def` so they compose with any
of the popular ASGI frameworks.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from .plugin import DDWPlugin, PluginTask
from .webhook import WebhookDispatcher
from .tenant import TenantStore, AuditEntry, UsageRecord


@dataclass
class HealthStatus:
    """Snapshot of plugin health."""

    ok: bool
    plugin_name: str
    version: str
    started: bool
    started_at: float = field(default_factory=time.time)


@dataclass
class HttpResponse:
    """A minimal HTTP response envelope (status + JSON body)."""

    status: int
    body: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "body": self.body}


# -----------------------------------------------------------------------------
# Handlers (framework-agnostic)
# -----------------------------------------------------------------------------


async def handle_health(plugin: DDWPlugin) -> HttpResponse:
    """`GET /health`."""
    return HttpResponse(
        status=200,
        body={
            "ok": plugin.started,
            "name": plugin.name,
            "version": plugin.version,
            "started": plugin.started,
        },
    )


async def handle_execute(
    plugin: DDWPlugin,
    request: dict[str, Any],
) -> HttpResponse:
    """`POST /execute` — accept a task envelope and run it."""
    if not isinstance(request, dict):
        return HttpResponse(400, {"error": "request must be a JSON object"})
    task = PluginTask.from_dict(request)
    if not task.task_id:
        task.task_id = str(uuid.uuid4())
    result = await plugin.execute(task)
    return HttpResponse(200 if result.ok else 500, result.to_dict())


async def handle_webhook(
    dispatcher: WebhookDispatcher,
    event: str,
    payload: dict[str, Any],
) -> HttpResponse:
    """`POST /webhook/dispatch` — fire a webhook event to subscribers."""
    if not event:
        return HttpResponse(400, {"error": "event is required"})
    records = await dispatcher.dispatch(event, payload)
    return HttpResponse(
        200,
        {
            "event": event,
            "delivered": len(records),
            "records": [r.to_dict() for r in records],
        },
    )


async def handle_tenant_usage(
    store: TenantStore,
    tenant_id: str,
) -> HttpResponse:
    """`GET /tenants/{tenant_id}/usage` — return the tenant's usage snapshot."""
    if not tenant_id:
        return HttpResponse(400, {"error": "tenant_id is required"})
    within, daily, monthly = store.usage_within_budget(tenant_id)
    return HttpResponse(
        200,
        {
            "tenant_id": tenant_id,
            "daily_tokens": daily,
            "monthly_tokens": monthly,
            "within_budget": within,
        },
    )


async def handle_audit(
    store: TenantStore,
    tenant_id: str | None = None,
) -> HttpResponse:
    """`GET /audit` — return the audit log (optionally filtered by tenant)."""
    entries = store.audit_log(tenant_id)
    return HttpResponse(
        200,
        {
            "count": len(entries),
            "entries": [
                {
                    "tenant_id": e.tenant_id,
                    "user_id": e.user_id,
                    "action": e.action,
                    "detail": e.detail,
                    "ts": e.ts,
                }
                for e in entries
            ],
        },
    )


# -----------------------------------------------------------------------------
# Optional FastAPI mount (only if fastapi is installed)
# -----------------------------------------------------------------------------


def try_build_fastapi_app(
    plugin: DDWPlugin,
    dispatcher: WebhookDispatcher,
    tenant_store: TenantStore,
) -> Any | None:
    """Build a FastAPI app if `fastapi` is importable; otherwise return None.

    The CLI doesn't require FastAPI — the framework-agnostic handlers above
    are enough. This helper is provided so production deployments can
    mount the CLI as a Hub plugin with one line of glue.
    """
    try:
        from fastapi import FastAPI, HTTPException  # type: ignore
    except ImportError:
        return None

    app = FastAPI(title=f"ddw-code-cli plugin ({plugin.name})")

    @app.get("/health")
    async def health() -> dict[str, Any]:
        resp = await handle_health(plugin)
        if resp.status != 200:
            raise HTTPException(status_code=resp.status, detail=resp.body)
        return resp.body

    @app.post("/execute")
    async def execute(request: dict[str, Any]) -> dict[str, Any]:
        resp = await handle_execute(plugin, request)
        if resp.status != 200:
            raise HTTPException(status_code=resp.status, detail=resp.body)
        return resp.body

    @app.post("/webhook/dispatch")
    async def webhook(event: str, payload: dict[str, Any]) -> dict[str, Any]:
        resp = await handle_webhook(dispatcher, event, payload)
        if resp.status != 200:
            raise HTTPException(status_code=resp.status, detail=resp.body)
        return resp.body

    @app.get("/tenants/{tenant_id}/usage")
    async def tenant_usage(tenant_id: str) -> dict[str, Any]:
        resp = await handle_tenant_usage(tenant_store, tenant_id)
        if resp.status != 200:
            raise HTTPException(status_code=resp.status, detail=resp.body)
        return resp.body

    @app.get("/audit")
    async def audit(tenant_id: str | None = None) -> dict[str, Any]:
        resp = await handle_audit(tenant_store, tenant_id)
        return resp.body

    return app


__all__ = [
    "HealthStatus",
    "HttpResponse",
    "handle_health",
    "handle_execute",
    "handle_webhook",
    "handle_tenant_usage",
    "handle_audit",
    "try_build_fastapi_app",
]
