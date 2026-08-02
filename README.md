# minimax-agent

A Claude Code-style Python CLI coding agent powered by **MiniMax Token Plan**.

`minimax-agent` is a self-contained, single-binary-style CLI that pairs a
pluggable model provider with a tool-using agent loop. It is designed
to feel familiar to anyone who has used Claude Code, while staying
small enough to read end-to-end (~1k lines of code) and embed inside
other products.

## Features

- **Agent loop** with `max_turns=15` cap, micro-compact at 60% context,
  and full streaming output.
- **OpenAI-compatible provider** for MiniMax Token Plan
  (`sk-cp-...`), with SSE streaming, function calling, and
  exponential-backoff retries on 429/503.
- **Eight built-in tools**: `file_read`, `file_write`, `file_edit`,
  `bash`, `grep` (ripgrep with a pure-Python fallback), `glob`,
  `web_search` (DuckDuckGo HTML), and `todo`.
- **Four-level permission model** (`allow` / `ask` / `deny` /
  `force_ask`) with dangerous-command detection (`rm -rf /`, `sudo`,
  `git push --force`, ...) and a forbidden-path guard (`~/.ssh`,
  `~/.gnupg`, `/etc/shadow`, ...).
- **Sandbox mode** that forces user confirmation for every mutating
  tool, for use on shared hosts.
- **Project context detection** — automatically loads
  `AGENTS.md` / `CLAUDE.md` / `README.md` and identifies the project
  language (Python / Node / Go / Rust / Java / Ruby).

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Set your Token Plan API key:

```bash
export MINIMAX_API_KEY="sk-cp-..."
```

## Usage

```bash
# One-shot: print result and exit.
minimax-agent --print "Write a hello world Python script"

# Interactive REPL.
minimax-agent

# Pipe-friendly.
echo "Read README.md" | minimax-agent --print

# Auto-approve mutating tools (CI / sandbox use).
minimax-agent --print --auto-approve "refactor foo.py"

# Tighter permissions.
minimax-agent --sandbox
```

## CLI

| Flag | Description |
| --- | --- |
| `--print` | Non-interactive: run once, print, exit. |
| `--api-key` | MiniMax API key (or set `MINIMAX_API_KEY`). |
| `--base-url` | Override the API base URL. |
| `--model` | Override the model name (default `MiniMax-Text-01`). |
| `--max-turns` | Max tool-call iterations per turn (default 15). |
| `--workspace` | Working directory (default: cwd). |
| `--sandbox` | Force confirmation for mutating tools. |
| `--auto-approve` | Skip all permission prompts. |
| `--verbose`, `-v` | Verbose logging to stderr. |

## Configuration

`minimax-agent` reads the following env vars (CLI flags override):

| Variable | Default | Purpose |
| --- | --- | --- |
| `MINIMAX_API_KEY` | — | **Required.** Token Plan key (`sk-cp-...`). |
| `MINIMAX_TOKEN` | — | Alias for `MINIMAX_API_KEY`. |
| `MINIMAX_BASE_URL` | `https://api.minimaxi.com/v1` | API endpoint. |
| `MINIMAX_MODEL` | `MiniMax-Text-01` | Model name. |
| `MINIMAX_MAX_TURNS` | `15` | Max tool-call iterations per turn. |

## Architecture

```
minimax_agent/
├── cli.py                 # argparse + REPL
├── turn_loop.py           # agent loop (async generator)
├── config.py              # env/CLI config loader
├── providers/
│   ├── base.py            # ModelProvider ABC
│   └── minimax.py         # MiniMax API adapter (SSE + retries)
├── tools/
│   ├── registry.py        # Tool dataclass + ToolRegistry
│   ├── dispatcher.py      # permission + schema validation
│   ├── builder.py         # one-shot default registry
│   ├── file_read.py / file_write.py / file_edit.py
│   ├── bash.py / grep.py / glob.py
│   ├── web_search.py / todo.py
├── compact/
│   ├── micro_compact.py   # 60% threshold, zero-LLM, pure string replace
│   └── auto_compact.py    # LLM-summarized fallback (skeleton)
├── security/
│   ├── permissions.py     # 4-level permission model
│   └── danger_check.py    # dangerous commands + forbidden paths
└── context/
    └── detector.py        # language + AGENTS.md / README.md loader
```

## Testing

```bash
pip install -e ".[dev]"
pytest
pytest --cov=minimax_agent
```

The current suite has **98 tests** with **86% line coverage** (target
was 30 tests / 80% coverage).

## End-to-end smoke tests

```bash
# Help works.
minimax-agent --help

# Missing key fails gracefully with exit code 2.
unset MINIMAX_API_KEY
minimax-agent --print "hi" ; echo "exit=$?"

# With a real key, --print returns streaming text.
export MINIMAX_API_KEY="sk-cp-..."
minimax-agent --print "Write a hello world Python script"
minimax-agent --print "Read the file README.md"
minimax-agent --print "List files in current directory"
```

## Safety

By default:

- `file_read` / `grep` / `glob` / `web_search` / `todo` are allowed.
- `file_write` / `file_edit` / `bash` ask once per session, then
  remember the answer.
- Path reads against `~/.ssh`, `~/.gnupg`, `~/.aws/credentials`,
  `/etc/shadow`, etc. are refused.
- Shell commands matching `rm -rf /`, `sudo ...`, `git push --force`,
  `dd if=... of=/dev/sd*`, fork bombs, and a dozen other patterns are
  refused outright.

Run with `--sandbox` to flip mutating tools to `force_ask`.

## License

Apache-2.0. See `LICENSE`.
