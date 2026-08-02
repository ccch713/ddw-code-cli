"""Multi-tenant scoping: per-tenant config, usage counters, and audit log.

A "tenant" is the unit of isolation in the Hub. Each tenant has its own
configuration, accumulates token usage, and gets its own audit trail.
For local use the in-process store is enough; in production this is
backed by the Hub's database.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

_TENANT_DIR = Path(os.path.expanduser("~/.ddw-code/tenants"))


@dataclass
class TenantConfig:
    """Per-tenant knobs."""

    tenant_id: str
    daily_token_limit: int = 1_000_000
    monthly_token_limit: int = 20_000_000
    allowed_models: list[str] = field(default_factory=list)
    blocked_tools: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "daily_token_limit": self.daily_token_limit,
            "monthly_token_limit": self.monthly_token_limit,
            "allowed_models": list(self.allowed_models),
            "blocked_tools": list(self.blocked_tools),
            "extra": dict(self.extra),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TenantConfig":
        return cls(
            tenant_id=str(data.get("tenant_id") or ""),
            daily_token_limit=int(data.get("daily_token_limit") or 1_000_000),
            monthly_token_limit=int(data.get("monthly_token_limit") or 20_000_000),
            allowed_models=list(data.get("allowed_models") or []),
            blocked_tools=list(data.get("blocked_tools") or []),
            extra=dict(data.get("extra") or {}),
        )


@dataclass
class UsageRecord:
    """One token-usage increment."""

    tenant_id: str
    user_id: str
    model: str
    input_tokens: int
    output_tokens: int
    ts: float = field(default_factory=time.time)


@dataclass
class AuditEntry:
    """One line in the audit log."""

    tenant_id: str
    user_id: str
    action: str
    detail: str = ""
    ts: float = field(default_factory=time.time)


class TenantStore:
    """File-backed multi-tenant state."""

    def __init__(self, base: Path | None = None) -> None:
        self.base = base or _TENANT_DIR
        self.base.mkdir(parents=True, exist_ok=True)
        self._usage: dict[str, list[UsageRecord]] = defaultdict(list)
        self._audit: list[AuditEntry] = []

    # ---- config -----------------------------------------------------------

    def get_config(self, tenant_id: str) -> TenantConfig:
        path = self.base / f"{self._safe(tenant_id)}.json"
        if not path.exists():
            return TenantConfig(tenant_id=tenant_id)
        try:
            return TenantConfig.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            return TenantConfig(tenant_id=tenant_id)

    def set_config(self, config: TenantConfig) -> None:
        path = self.base / f"{self._safe(config.tenant_id)}.json"
        path.write_text(
            json.dumps(config.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ---- usage ------------------------------------------------------------

    def record_usage(self, record: UsageRecord) -> None:
        self._usage[record.tenant_id].append(record)

    def usage_total(
        self,
        tenant_id: str,
        since_ts: float | None = None,
    ) -> tuple[int, int]:
        """Return (input_tokens, output_tokens) for the tenant since `since_ts`."""
        in_t = 0
        out_t = 0
        for r in self._usage.get(tenant_id, []):
            if since_ts is not None and r.ts < since_ts:
                continue
            in_t += r.input_tokens
            out_t += r.output_tokens
        return in_t, out_t

    def usage_within_budget(
        self,
        tenant_id: str,
        daily_window_s: float = 86400.0,
        monthly_window_s: float = 30 * 86400.0,
    ) -> tuple[bool, int, int]:
        """Return (within_budget, daily_total, monthly_total)."""
        now = time.time()
        in_d, out_d = self.usage_total(tenant_id, since_ts=now - daily_window_s)
        in_m, out_m = self.usage_total(tenant_id, since_ts=now - monthly_window_s)
        daily = in_d + out_d
        monthly = in_m + out_m
        cfg = self.get_config(tenant_id)
        within = daily <= cfg.daily_token_limit and monthly <= cfg.monthly_token_limit
        return within, daily, monthly

    # ---- audit ------------------------------------------------------------

    def append_audit(self, entry: AuditEntry) -> None:
        self._audit.append(entry)

    def audit_log(self, tenant_id: str | None = None) -> list[AuditEntry]:
        if tenant_id is None:
            return list(self._audit)
        return [e for e in self._audit if e.tenant_id == tenant_id]

    # ---- helpers ----------------------------------------------------------

    @staticmethod
    def _safe(tenant_id: str) -> str:
        return "".join(c for c in tenant_id if c.isalnum() or c in "-_.") or "default"


__all__ = [
    "TenantStore",
    "TenantConfig",
    "UsageRecord",
    "AuditEntry",
]
