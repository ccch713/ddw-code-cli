"""DDW AI Hub integration: plugin lifecycle, REST handlers, webhooks, tenants."""
from __future__ import annotations

from .plugin import DDWPlugin, PluginResult, PluginTask, TaskHandler
from .rest import (
    HealthStatus,
    HttpResponse,
    handle_audit,
    handle_execute,
    handle_health,
    handle_tenant_usage,
    handle_webhook,
    try_build_fastapi_app,
)
from .tenant import AuditEntry, TenantConfig, TenantStore, UsageRecord
from .webhook import WebhookDispatcher, WebhookEndpoint, WebhookEvent

__all__ = [
    "DDWPlugin",
    "PluginResult",
    "PluginTask",
    "TaskHandler",
    "HealthStatus",
    "HttpResponse",
    "handle_audit",
    "handle_execute",
    "handle_health",
    "handle_tenant_usage",
    "handle_webhook",
    "try_build_fastapi_app",
    "AuditEntry",
    "TenantConfig",
    "TenantStore",
    "UsageRecord",
    "WebhookDispatcher",
    "WebhookEndpoint",
    "WebhookEvent",
]
