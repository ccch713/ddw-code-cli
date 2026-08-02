# Documentation

Welcome to the `minimax-agent` documentation. This directory contains detailed guides for understanding, using, and extending the agent.

## Table of Contents

### For Users

- **[README.md](../README.md)** - Quick start guide, installation, and basic usage
- **[CHANGELOG.md](../CHANGELOG.md)** - Version history and release notes

### For Developers

- **[architecture.md](architecture.md)** - System architecture and design decisions
- **[tools.md](tools.md)** - Built-in tools reference with parameters and examples
- **[security.md](security.md)** - Security model, permission system, and safety features
- **[providers.md](providers.md)** - Model provider architecture and how to add new providers

### Contributing

- **[CONTRIBUTING.md](../CONTRIBUTING.md)** - Development setup, testing, code style, and PR process

## Quick Links

### Getting Started

1. **Install**: `pip install -e ".[dev]"`
2. **Set API key**: `export MINIMAX_API_KEY="sk-cp-..."`
3. **Run**: `minimax-agent --print "Hello, world!"`

### Common Tasks

| Task | Documentation |
|------|---------------|
| Understand the architecture | [architecture.md](architecture.md) |
| Use built-in tools | [tools.md](tools.md) |
| Configure security settings | [security.md](security.md) |
| Add a new model provider | [providers.md](providers.md) |
| Add a new tool | [CONTRIBUTING.md](../CONTRIBUTING.md#adding-new-tools) |
| Run tests | [CONTRIBUTING.md](../CONTRIBUTING.md#running-tests) |
| Report a bug | [CONTRIBUTING.md](../CONTRIBUTING.md#reporting-issues) |

### API Reference

#### Tools

| Tool | Description | Permission |
|------|-------------|------------|
| `file_read` | Read file contents | `allow` |
| `file_write` | Write to file | `ask` |
| `file_edit` | Edit file (search/replace) | `ask` |
| `bash` | Execute shell command | `ask` |
| `grep` | Search file contents | `allow` |
| `glob` | Find files by pattern | `allow` |
| `web_search` | DuckDuckGo web search | `allow` |
| `todo` | Manage session task list | `allow` |

See [tools.md](tools.md) for detailed parameters and examples.

#### Providers

| Provider | API Format | Status |
|----------|------------|--------|
| MiniMax | OpenAI-compatible | Built-in |
| Custom | Any | See [providers.md](providers.md) |

#### Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `MINIMAX_API_KEY` | API key (required) | - |
| `MINIMAX_BASE_URL` | API endpoint | `https://api.minimaxi.com/v1` |
| `MINIMAX_MODEL` | Model name | `MiniMax-Text-01` |
| `MINIMAX_MAX_TURNS` | Max agent turns | `15` |
| `MINIMAX_SANDBOX` | Enable sandbox mode | `0` |

See [config.py](../minimax_agent/config.py) for full configuration options.

## Architecture Overview

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

See [architecture.md](architecture.md) for detailed explanation.

## Security Model

The agent implements four layers of security:

1. **Permission Levels**: `allow`, `ask`, `deny`, `force_ask`
2. **Dangerous Command Detection**: Pattern matching for destructive commands
3. **Forbidden Path Guard**: Blocks access to sensitive files
4. **Sandbox Mode**: Forces confirmation for all mutations

See [security.md](security.md) for details.

## Development

### Prerequisites

- Python 3.10+ (3.11+ recommended)
- Git

### Setup

```bash
git clone https://github.com/ccch713/minimax-agent.git
cd minimax-agent
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=minimax_agent

# Run specific test
pytest tests/test_tools.py::test_file_read
```

### Code Style

```bash
# Check for lint issues
ruff check .

# Format code
ruff format .
```

See [CONTRIBUTING.md](../CONTRIBUTING.md) for complete guidelines.

## Support

- **Issues**: [GitHub Issues](https://github.com/ccch713/minimax-agent/issues)
- **Discussions**: [GitHub Discussions](https://github.com/ccch713/minimax-agent/discussions)
- **Security**: See [security.md](security.md#reporting-security-issues)

## License

Apache-2.0. See [LICENSE](../LICENSE).
