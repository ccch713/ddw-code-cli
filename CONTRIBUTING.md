# Contributing to minimax-agent

Thank you for your interest in contributing! This guide will help you get started.

## Development Setup

### Prerequisites

- Python 3.10 or later (3.11+ recommended)
- Git

### Getting Started

```bash
# Clone the repository
git clone https://github.com/ccch713/minimax-agent.git
cd minimax-agent

# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install in development mode with all dev dependencies
pip install -e ".[dev]"
```

## Running Tests

```bash
# Run the full test suite
pytest

# Run with verbose output
pytest -v

# Run with coverage report
pytest --cov=minimax_agent

# Run a specific test file
pytest tests/test_tools.py

# Run a specific test
pytest tests/test_tools.py::test_file_read
```

## Code Style

This project uses [Ruff](https://docs.astral.sh/ruff/) for linting and formatting.

```bash
# Check for lint issues
ruff check .

# Auto-fix lint issues
ruff check --fix .

# Format code
ruff format .
```

### Style Rules

- Line length: 110 characters
- Target Python version: 3.10
- Enabled rule sets: `E`, `F`, `W`, `I`, `B`, `UP`

## Pull Request Process

1. **Fork** the repository and create a branch from `main`.
2. **Write tests** for new functionality. Aim for at least 80% coverage on new code.
3. **Update documentation** if your change affects the public API or user-facing behavior.
4. **Run the full test suite** before submitting:
   ```bash
   pytest --cov=minimax_agent
   ruff check .
   ruff format --check .
   ```
5. **Write a clear PR description** explaining what changed and why.

### PR Title Format

Use conventional commits:
- `feat: add new tool for X`
- `fix: handle edge case in Y`
- `docs: update architecture guide`
- `test: add tests for Z`
- `refactor: simplify W`

## Reporting Issues

When reporting bugs, please include:

1. **Python version** (`python --version`)
2. **Operating system** and version
3. **Steps to reproduce** the issue
4. **Expected behavior** vs actual behavior
5. **Error output** (if any), including full traceback

## Adding New Tools

To add a new tool:

1. Create `minimax_agent/tools/your_tool.py` with:
   - An async handler function
   - A `schema()` function returning the JSON schema for the tool's input
2. Register the tool in `minimax_agent/tools/builder.py`
3. Add a default permission policy in `minimax_agent/security/permissions.py`
4. Add tests in `tests/test_tools.py`
5. Update `docs/tools.md`

## Adding New Providers

To add a new LLM provider:

1. Create `minimax_agent/providers/your_provider.py` implementing `ModelProvider`
2. Register it in `minimax_agent/providers/__init__.py`
3. Add configuration options to `minimax_agent/config.py`
4. Add tests in `tests/test_minimax_provider.py` (or a new file)
5. Update `docs/providers.md`

## License

By contributing, you agree that your contributions will be licensed under the [Apache-2.0 License](LICENSE).
