# Providers Guide

This document explains how model providers work in `minimax-agent` and how to add new ones.

## Overview

Providers are pluggable backends that translate chat requests into API calls and stream back responses. The architecture supports any OpenAI-compatible API out of the box, and custom providers can be added by implementing the `ModelProvider` abstract base class.

## Built-in Providers

### MiniMax (Default)

The default provider for MiniMax Token Plan (`sk-cp-...` keys).

**Endpoint:** `https://api.minimaxi.com/v1`

**Features:**
- OpenAI-compatible chat completions API
- SSE streaming
- Function calling (tool use)
- Exponential backoff retries on 429/503
- Token counting (approximate)

**Configuration:**
```bash
export MINIMAX_API_KEY="sk-cp-..."
export MINIMAX_BASE_URL="https://api.minimaxi.com/v1"  # optional
export MINIMAX_MODEL="MiniMax-Text-01"  # optional
```

## Provider Architecture

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  Agent Loop  │────▶│   Provider   │────▶│  External    │
│              │◀────│  (abstract)  │◀────│  API         │
└──────────────┘     └──────────────┘     └──────────────┘
```

### Abstract Base Class

All providers implement `ModelProvider` from `minimax_agent/providers/base.py`:

```python
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

class ModelProvider(ABC):
    name: str = "base"

    @abstractmethod
    async def chat(self, request: ChatRequest) -> AsyncIterator[StreamEvent]:
        """Stream a chat completion. Must be an async generator."""
        raise NotImplementedError

    @abstractmethod
    def count_tokens(self, text: str) -> int:
        """Approximate token count for a piece of text."""
        raise NotImplementedError
```

### Data Structures

#### ChatRequest

```python
@dataclass
class ChatRequest:
    system: str                                    # System prompt
    messages: list[dict[str, Any]]                 # Conversation history
    tools: list[dict[str, Any]] = field(...)       # Tool definitions
    model: str | None = None                       # Model override
    max_tokens: int = 4096                         # Max response tokens
    temperature: float = 0.2                       # Sampling temperature
```

#### StreamEvent

```python
@dataclass
class StreamEvent:
    text_delta: str | None = None      # Incremental text chunk
    tool_use: ToolUseBlock | None = None  # Complete tool call
    usage: Usage | None = None         # Token usage (at end)
    stop_reason: str | None = None     # "stop", "tool_calls", "error"
    error: str | None = None           # Error message
    final_text: str = ""               # Coalesced full text
```

#### ToolUseBlock

```python
@dataclass
class ToolUseBlock:
    id: str                            # Unique tool call ID
    name: str                          # Tool name
    input: dict[str, Any]              # Tool arguments
```

#### Usage

```python
@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
```

## Adding a New Provider

### Step 1: Create Provider File

Create `minimax_agent/providers/your_provider.py`:

```python
"""Your custom provider implementation."""
from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx

from .base import ChatRequest, ModelProvider, StreamEvent, ToolUseBlock, Usage

logger = logging.getLogger(__name__)


class YourProvider(ModelProvider):
    """Your custom LLM provider."""

    name = "your_provider"

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.example.com/v1",
        *,
        timeout: float = 120.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("YourProvider requires a non-empty api_key")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._client = client or httpx.AsyncClient(timeout=timeout)
        self._owns_client = client is None

    async def aclose(self) -> None:
        """Clean up the HTTP client."""
        if self._owns_client:
            await self._client.aclose()

    async def chat(self, request: ChatRequest) -> AsyncIterator[StreamEvent]:
        """Stream a chat completion."""
        payload = self._build_payload(request)
        
        # Make streaming request
        url = f"{self._base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }

        async with self._client.stream(
            "POST", url, json=payload, headers=headers
        ) as response:
            if response.status_code >= 400:
                await response.aread()
                yield StreamEvent(
                    error=f"HTTP {response.status_code}",
                    stop_reason="error",
                )
                return

            # Parse SSE stream
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    yield StreamEvent(stop_reason="stop")
                    return
                
                chunk = json.loads(data)
                # Process chunk and yield StreamEvents
                # (Implementation depends on API format)
                yield StreamEvent(text_delta=chunk.get("choices", [{}])[0].get("delta", {}).get("content", ""))

    def count_tokens(self, text: str) -> int:
        """Approximate token count."""
        if not text:
            return 0
        return max(1, int(len(text) * 0.25))  # ~4 chars per token

    def _build_payload(self, request: ChatRequest) -> dict[str, Any]:
        """Translate ChatRequest to API format."""
        messages = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        messages.extend(request.messages)

        payload = {
            "model": request.model or "your-default-model",
            "messages": messages,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "stream": True,
        }

        if request.tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t.get("description", ""),
                        "parameters": t.get("input_schema", {"type": "object", "properties": {}}),
                    },
                }
                for t in request.tools
            ]
            payload["tool_choice"] = "auto"

        return payload
```

### Step 2: Register the Provider

Add to `minimax_agent/providers/__init__.py`:

```python
from .base import ModelProvider
from .minimax import MiniMaxProvider
from .your_provider import YourProvider

PROVIDERS: dict[str, type[ModelProvider]] = {
    "minimax": MiniMaxProvider,
    "your_provider": YourProvider,
}

def get_provider(name: str, **kwargs) -> ModelProvider:
    """Get a provider instance by name."""
    if name not in PROVIDERS:
        raise ValueError(f"Unknown provider: {name}. Available: {list(PROVIDERS.keys())}")
    return PROVIDERS[name](**kwargs)
```

### Step 3: Add Configuration

Update `minimax_agent/config.py`:

```python
@dataclass(frozen=True)
class Config:
    # ... existing fields ...
    provider: str = "minimax"  # or "your_provider"
    # Add provider-specific env vars
```

### Step 4: Add Tests

Create `tests/test_your_provider.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from minimax_agent.providers.your_provider import YourProvider

@pytest.fixture
def provider():
    return YourProvider(api_key="test-key")

@pytest.mark.asyncio
async def test_chat_streaming(provider):
    # Mock the HTTP client
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.aiter_lines = AsyncMock(return_value=iter([
        'data: {"choices":[{"delta":{"content":"Hello"}}]}',
        'data: [DONE]',
    ]))
    
    provider._client.stream = MagicMock(return_value=mock_response)
    
    from minimax_agent.providers.base import ChatRequest
    request = ChatRequest(
        system="You are a helpful assistant.",
        messages=[{"role": "user", "content": "Hi"}],
    )
    
    events = []
    async for event in provider.chat(request):
        events.append(event)
    
    assert any(e.text_delta == "Hello" for e in events)
    assert any(e.stop_reason == "stop" for e in events)
```

### Step 5: Update Documentation

Add your provider to this file (`docs/providers.md`).

## Provider Comparison

| Provider | API Format | Streaming | Tool Use | Retries |
|----------|------------|-----------|----------|---------|
| MiniMax | OpenAI-compatible | SSE | Yes | 3x backoff |
| Your Provider | ? | ? | ? | ? |

## Best Practices

### Error Handling

- Yield `StreamEvent(error=..., stop_reason="error")` for API errors
- Don't raise exceptions from `chat()` — let the agent loop handle errors
- Log errors for debugging

### Streaming

- Use SSE (Server-Sent Events) for streaming
- Buffer tool call arguments until complete
- Yield `text_delta` events for real-time output
- Yield `tool_use` events only when arguments are complete

### Token Counting

- Approximate is fine (±20%)
- Used for budget heuristics, not billing
- Default: ~4 characters per token

### Retries

- Retry on 429, 500, 502, 503, 504
- Use exponential backoff with jitter
- Max 3 retries by default
- Log retry attempts

## OpenAI-Compatible APIs

Many providers offer OpenAI-compatible endpoints. To use them:

1. Set `MINIMAX_BASE_URL` to the provider's endpoint
2. Set `MINIMAX_API_KEY` to your key
3. Use the `minimax` provider (it's OpenAI-compatible)

**Examples:**
- OpenAI: `https://api.openai.com/v1`
- Azure OpenAI: `https://your-resource.openai.azure.com/openai/deployments/your-deployment/`
- Anthropic (via proxy): `https://api.anthropic.com/v1`
- Local models (Ollama, vLLM): `http://localhost:11434/v1`

## Security Considerations

- **Never log API keys** in production
- **Validate responses** before yielding
- **Sanitize error messages** (don't leak internal details)
- **Use HTTPS** for all API calls
- **Timeout requests** to prevent hanging

## Troubleshooting

### Common Issues

**"Provider not found"**
- Check provider name in `PROVIDERS` dict
- Ensure provider is registered in `__init__.py`

**"Streaming not working"**
- Verify API supports SSE streaming
- Check `Accept: text/event-stream` header
- Ensure client supports async streaming

**"Tool calls not working"**
- Verify API supports function calling
- Check tool schema format
- Ensure `tool_choice: "auto"` is set

**"Retries not working"**
- Check retryable status codes
- Verify backoff implementation
- Ensure logging is configured

## Further Reading

- [architecture.md](architecture.md) - Overall system architecture
- [tools.md](tools.md) - Tool reference
- [security.md](security.md) - Security model
