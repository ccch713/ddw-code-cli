"""MCP (Model Context Protocol) client with stdio and SSE/HTTP transports."""
from __future__ import annotations

from .client import MCPClient, MCPError, MCPManager, MCPServerConfig
from .sse import SseTransport
from .stdio import StdioTransport

__all__ = [
    "MCPClient",
    "MCPError",
    "MCPManager",
    "MCPServerConfig",
    "StdioTransport",
    "SseTransport",
]
