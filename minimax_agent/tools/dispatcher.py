"""Tool dispatcher: validate input, check permissions, invoke handler.

Wraps every tool call with:
1. Permission lookup (allow / ask / deny / force_ask).
2. Schema validation against the tool's declared JSON schema.
3. Exception capture (tool errors must never crash the agent loop).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from ..security.permissions import Decision, PermissionManager
from .registry import ToolRegistry


class ToolDenied(RuntimeError):
    """Raised when a tool is denied by the permission policy."""


class ToolNeedsConfirmation(RuntimeError):
    """Raised when a tool needs user confirmation before running.

    The caller is expected to catch this, prompt the user, and re-dispatch.
    """

    def __init__(self, tool_name: str) -> None:
        super().__init__(f"tool {tool_name!r} needs confirmation")
        self.tool_name = tool_name


@dataclass
class DispatchResult:
    """The outcome of dispatching a single tool call."""

    tool_name: str
    output: str
    is_error: bool = False


def _validate(instance: dict[str, Any], schema: dict[str, Any]) -> str | None:
    """Very small JSON-schema validator covering `required` and primitive types.

    Returns None on success, or a human-readable error string.
    """
    if schema.get("type") == "object" or "properties" in schema:
        for req in schema.get("required", []):
            if req not in instance:
                return f"missing required field: {req!r}"
        props = schema.get("properties", {})
        for k, v in instance.items():
            if k not in props:
                continue
            expected = props[k].get("type")
            if expected is None:
                continue
            py_type = {
                "string": str,
                "integer": int,
                "number": (int, float),
                "boolean": bool,
                "array": list,
                "object": dict,
            }.get(expected)
            if py_type is None:
                continue
            # bool is a subclass of int in Python — guard against that footgun.
            if expected == "integer" and isinstance(v, bool):
                return f"field {k!r}: expected integer, got boolean"
            if expected == "string" and not isinstance(v, str):
                return f"field {k!r}: expected string"
            if not isinstance(v, py_type):
                return f"field {k!r}: expected {expected}"
    return None


class ToolDispatcher:
    """Routes tool calls to handlers, enforcing permissions and validation."""

    def __init__(
        self,
        registry: ToolRegistry,
        permissions: PermissionManager,
    ) -> None:
        self.registry = registry
        self.permissions = permissions

    async def dispatch(self, name: str, arguments: dict[str, Any] | str) -> DispatchResult:
        """Run a tool by name with the given arguments.

        - `arguments` may already be a dict (preferred) or a JSON string.
        - Any error is captured into the result so the loop can continue.
        """
        try:
            tool = self.registry.get(name)
        except KeyError as e:
            return DispatchResult(name, str(e), is_error=True)

        decision = self.permissions.decide(name)
        if decision == Decision.DENY:
            return DispatchResult(
                name,
                f"tool {name!r} is denied by policy",
                is_error=True,
            )
        if decision in {Decision.ASK, Decision.FORCE_ASK}:
            if decision == Decision.FORCE_ASK or name not in self.permissions.approved:
                raise ToolNeedsConfirmation(name)

        # Coerce string args to dict.
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments) if arguments.strip() else {}
            except json.JSONDecodeError as e:
                return DispatchResult(name, f"invalid JSON arguments: {e}", is_error=True)
        if arguments is None:
            arguments = {}

        # Validate.
        err = _validate(arguments, tool.input_schema)
        if err is not None:
            return DispatchResult(name, f"validation error: {err}", is_error=True)

        # Invoke.
        try:
            output = await tool.handler(**arguments)
        except Exception as e:  # noqa: BLE001 - we want to surface anything
            return DispatchResult(name, f"tool error: {e}", is_error=True)
        return DispatchResult(name, output, is_error=False)
