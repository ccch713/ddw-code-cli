"""MCP (Model Context Protocol) client.

The MCP spec lets an editor / host talk to remote "servers" that expose
tools, prompts, and resources. We implement the minimum surface area the
DDW Code CLI needs:

- `connect(server_config)` — open a session with a server
- `list_tools()`          — fetch its tool catalogue
- `call_tool(name, args)` — invoke a tool and return its result

Two transports are supported:

- `stdio` — spawn a child process and speak JSON-RPC over its stdin/stdout
- `sse`   — open an HTTP connection with server-sent events

The transport details are isolated to `stdio.py` and `sse.py` so the
client only deals with framed JSON-RPC messages.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .stdio import StdioTransport
from .sse import SseTransport


@dataclass
class MCPServerConfig:
    """Connection details for one MCP server."""

    name: str
    transport: str = "stdio"  # 'stdio' | 'sse'
    command: list[str] = field(default_factory=list)  # for stdio
    url: str = ""  # for sse
    headers: dict[str, str] = field(default_factory=dict)  # for sse
    cwd: str | None = None
    env: dict[str, str] = field(default_factory=dict)


class MCPError(RuntimeError):
    """Raised when an MCP call fails."""


class MCPClient:
    """A connected MCP client session."""

    def __init__(self, config: MCPServerConfig) -> None:
        self.config = config
        self._transport: StdioTransport | SseTransport | None = None
        self._tools: list[dict[str, Any]] = []
        self._next_id = 1

    async def connect(self) -> None:
        """Open the transport. After this returns the client is ready."""
        if self.config.transport == "stdio":
            if not self.config.command:
                raise MCPError("stdio transport requires `command`")
            t = StdioTransport(
                command=self.config.command,
                cwd=self.config.cwd,
                env={**os.environ, **self.config.env},
            )
        elif self.config.transport == "sse":
            if not self.config.url:
                raise MCPError("sse transport requires `url`")
            t = SseTransport(url=self.config.url, headers=self.config.headers)
        else:
            raise MCPError(f"unsupported transport: {self.config.transport!r}")
        await t.start()
        self._transport = t

    async def aclose(self) -> None:
        if self._transport is not None:
            await self._transport.close()
            self._transport = None

    async def __aenter__(self) -> "MCPClient":
        await self.connect()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    def _next_request_id(self) -> int:
        i = self._next_id
        self._next_id += 1
        return i

    async def _request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if self._transport is None:
            raise MCPError("not connected; call connect() first")
        req = {
            "jsonrpc": "2.0",
            "id": self._next_request_id(),
            "method": method,
            "params": params or {},
        }
        await self._transport.send(json.dumps(req))
        # Read until we get a response with our id.
        deadline = time.time() + 30.0
        while time.time() < deadline:
            raw = await self._transport.recv()
            if raw is None:
                raise MCPError("transport closed before response")
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if "id" not in msg:
                continue
            if msg.get("id") != req["id"]:
                continue
            if "error" in msg:
                err = msg["error"]
                raise MCPError(
                    f"MCP {method} failed: {err.get('message', err)}"
                )
            return msg.get("result") or {}
        raise MCPError(f"MCP {method} timed out after 30s")

    async def initialize(self) -> dict[str, Any]:
        """Perform the MCP `initialize` handshake.

        Returns the server's `capabilities` dictionary (empty on minimal servers).
        """
        return await self._request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "ddw-code-cli", "version": "0.1.0"},
            },
        )

    async def list_tools(self) -> list[dict[str, Any]]:
        """Fetch the server's tool catalogue."""
        result = await self._request("tools/list")
        tools = result.get("tools") if isinstance(result, dict) else None
        self._tools = list(tools or [])
        return list(self._tools)

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        """Invoke a tool by name and return its structured result."""
        result = await self._request(
            "tools/call",
            {"name": name, "arguments": arguments or {}},
        )
        if not isinstance(result, dict):
            return result
        if result.get("isError"):
            content = result.get("content") or []
            msg = "; ".join(
                str(c.get("text", c)) for c in content if isinstance(c, dict)
            )
            raise MCPError(f"tool {name!r} returned error: {msg}")
        return result.get("content", result)


class MCPManager:
    """Process-wide manager for multiple MCP server connections."""

    def __init__(self) -> None:
        self._clients: dict[str, MCPClient] = {}

    async def connect(self, name: str, config: MCPServerConfig) -> MCPClient:
        if name in self._clients:
            return self._clients[name]
        client = MCPClient(config)
        await client.connect()
        try:
            await client.initialize()
        except MCPError:
            await client.aclose()
            raise
        self._clients[name] = client
        return client

    async def disconnect(self, name: str) -> bool:
        client = self._clients.pop(name, None)
        if client is None:
            return False
        await client.aclose()
        return True

    async def aclose(self) -> None:
        for name in list(self._clients):
            await self.disconnect(name)

    def get(self, name: str) -> MCPClient | None:
        return self._clients.get(name)

    def all(self) -> dict[str, MCPClient]:
        return dict(self._clients)


__all__ = [
    "MCPClient",
    "MCPError",
    "MCPManager",
    "MCPServerConfig",
]
