"""stdio transport for MCP: speak JSON-RPC over a child process's stdio."""
from __future__ import annotations

import asyncio
import os
from typing import Any


class StdioTransport:
    """An MCP stdio transport backed by `asyncio.create_subprocess_exec`."""

    def __init__(
        self,
        command: list[str],
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        if not command:
            raise ValueError("command must be a non-empty list")
        self.command = list(command)
        self.cwd = cwd
        self.env = env or dict(os.environ)
        self._proc: asyncio.subprocess.Process | None = None

    async def start(self) -> None:
        try:
            self._proc = await asyncio.create_subprocess_exec(
                *self.command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                cwd=self.cwd,
                env=self.env,
            )
        except FileNotFoundError as e:
            raise RuntimeError(f"failed to spawn {self.command[0]!r}: {e}") from e

    async def close(self) -> None:
        if self._proc is None:
            return
        if self._proc.stdin and not self._proc.stdin.is_closing():
            try:
                self._proc.stdin.close()
            except Exception:
                pass
        try:
            await asyncio.wait_for(self._proc.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            try:
                self._proc.kill()
            finally:
                pass
        self._proc = None

    async def send(self, payload: str) -> None:
        if self._proc is None or self._proc.stdin is None:
            raise RuntimeError("transport not started")
        data = (payload.rstrip("\n") + "\n").encode("utf-8")
        self._proc.stdin.write(data)
        await self._proc.stdin.drain()

    async def recv(self) -> str | None:
        if self._proc is None or self._proc.stdout is None:
            raise RuntimeError("transport not started")
        line = await self._proc.stdout.readline()
        if not line:
            return None
        return line.decode("utf-8", errors="replace").rstrip("\n")


__all__ = ["StdioTransport"]
