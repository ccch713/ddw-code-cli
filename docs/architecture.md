# Architecture

This document describes the high-level architecture of `minimax-agent`, a Claude Code-style CLI coding agent.

## Overview

`minimax-agent` is a single-binary-style CLI that pairs a pluggable model provider with a tool-using agent loop. The design prioritizes simplicity, readability, and ease of extension.

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   CLI Entry  │────▶│  Agent Loop  │────▶│   Provider   │
│   (cli.py)   │     │  (agent.py)  │     │  (minimax/)  │
└──────────────┘     └──────┬───────┘     └──────────────┘
                            │
                            ▼
                     ┌──────────────┐
                     │    Tools     │
                     │  (tools/)    │
                     └──────────────┘
```

## Core Components

### 1. CLI Entry (`cli.py`)

The command-line interface built with `argparse`. Supports:
- `--print` mode: one-shot execution, print result, exit
- `--sandbox` mode: force user confirmation for mutating tools
- `--auto-approve`: skip permission prompts (use with caution)
- `--model`: select provider/model
- `--max-turns`: override default turn limit (15)

### 2. Agent Loop (`agent.py`)

The heart of the system. Implements a streaming agent loop that:

1. **Sends** the conversation history to the provider
2. **Receives** a streamed response (text + tool calls)
3. **Executes** tool calls via the dispatcher
4. **Appends** results to conversation history
5. **Repeats** until the model stops calling tools or `max_turns` is reached

Key features:
- **Micro-compact** at 60% context window to prevent token overflow
- **Streaming output** via Rich console for real-time feedback
- **Error recovery** with exponential backoff on 429/503 responses

### 3. Providers (`providers/`)

Pluggable model backends implementing the `ModelProvider` protocol:

- **`minimax.py`**: OpenAI-compatible provider for MiniMax Token Plan
  - SSE streaming via `httpx`
  - Function calling (tool use)
  - Automatic retry with exponential backoff

Adding a new provider requires implementing:
```python
class ModelProvider(Protocol):
    async def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        stream: bool = True,
    ) -> AsyncIterator[StreamEvent]: ...
```

### 4. Tools (`tools/`)

Eight built-in tools, each with:
- An async handler function
- A JSON schema for input validation
- Permission defaults in `security/permissions.py`

| Tool | Description | Default Permission |
|------|-------------|-------------------|
| `file_read` | Read file contents | `allow` |
| `file_write` | Write to file | `ask` |
| `file_edit` | Edit file (search/replace) | `ask` |
| `bash` | Execute shell command | `ask` |
| `grep` | Search files (ripgrep + fallback) | `allow` |
| `glob` | Find files by pattern | `allow` |
| `web_search` | DuckDuckGo HTML search | `allow` |
| `todo` | Manage task list | `allow` |

Tool execution flow:
```
Tool Call Request
       │
       ▼
┌──────────────┐     ┌──────────────┐
│  Permission  │────▶│  Danger      │
│  Check       │     │  Detection   │
└──────────────┘     └──────────────┘
       │
       ▼
┌──────────────┐     ┌──────────────┐
│  Path Guard  │────▶│  Execution   │
└──────────────┘     └──────────────┘
```

### 5. Security (`security/`)

Four-layer security model:

1. **Permission Levels**: `allow`, `ask`, `deny`, `force_ask`
2. **Dangerous Command Detection**: Pattern matching for `rm -rf`, `sudo`, `git push --force`, etc.
3. **Forbidden Path Guard**: Blocks access to `~/.ssh`, `~/.gnupg`, `/etc/shadow`, etc.
4. **Sandbox Mode**: Forces `ask` for all mutating tools

### 6. Context Detection (`context/`)

Automatically loads project context:
- **Project files**: `AGENTS.md`, `CLAUDE.md`, `README.md`
- **Language detection**: Analyzes file extensions and config files
- **Injected** into system prompt for better code generation

### 7. Compaction (`compact/`)

Manages context window limits:
- **Auto-compact**: Triggered at 60% context usage
- **Micro-compact**: Summarizes older messages while preserving recent context
- **Token counting**: Estimates token usage for conversation history

## Data Flow

```
User Input
    │
    ▼
┌──────────────┐
│   CLI Parse  │
└──────────────┘
    │
    ▼
┌──────────────┐
│ Load Context │
│ (AGENTS.md)  │
└──────────────┘
    │
    ▼
┌──────────────┐     ┌──────────────┐
│  Agent Loop  │◀───▶│   Provider   │
└──────────────┘     └──────────────┘
    │
    ▼
┌──────────────┐
│ Tool Calls?  │──Yes──▶ Execute Tools
└──────────────┘         │
    │No                  │
    ▼                    │
┌──────────────┐         │
│   Output     │◀────────┘
└──────────────┘
```

## Configuration

Configuration is loaded from (in order of precedence):

1. **Command-line arguments** (highest priority)
2. **Environment variables** (`MINIMAX_API_KEY`, `MINIMAX_MODEL`, etc.)
3. **Config file** (`~/.config/minimax-agent/config.toml`)
4. **Defaults** (lowest priority)

## Extension Points

### Adding a New Tool

1. Create `minimax_agent/tools/your_tool.py`
2. Implement handler and schema
3. Register in `tools/builder.py`
4. Add permission default in `security/permissions.py`
5. Add tests

### Adding a New Provider

1. Create `minimax_agent/providers/your_provider.py`
2. Implement `ModelProvider` protocol
3. Register in `providers/__init__.py`
4. Add configuration in `config.py`
5. Add tests

## Dependencies

- **`httpx`**: Async HTTP client for API calls and web search
- **`rich`**: Terminal formatting, progress bars, syntax highlighting
- **`pytest`**: Testing framework (dev only)
- **`ruff`**: Linting and formatting (dev only)

## File Structure

```
minimax-agent/
├── minimax_agent/
│   ├── __init__.py
│   ├── cli.py              # CLI entry point
│   ├── agent.py            # Agent loop
│   ├── config.py           # Configuration
│   ├── providers/          # Model providers
│   │   ├── __init__.py
│   │   └── minimax.py      # MiniMax provider
│   ├── tools/              # Built-in tools
│   │   ├── __init__.py
│   │   ├── builder.py      # Tool registration
│   │   ├── dispatcher.py   # Tool execution
│   │   ├── registry.py     # Tool registry
│   │   ├── bash.py
│   │   ├── file_read.py
│   │   ├── file_write.py
│   │   ├── file_edit.py
│   │   ├── grep.py
│   │   ├── glob.py
│   │   ├── web_search.py
│   │   └── todo.py
│   ├── security/           # Security policies
│   │   ├── __init__.py
│   │   ├── permissions.py
│   │   └── danger_check.py
│   ├── context/            # Project context
│   │   ├── __init__.py
│   │   └── detector.py
│   └── compact/            # Context compaction
│       ├── __init__.py
│       ├── auto_compact.py
│       └── micro_compact.py
├── tests/                  # Test suite
├── docs/                   # Documentation
├── pyproject.toml          # Project metadata
└── README.md
```
