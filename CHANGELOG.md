# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-08-02

### Added
- Agent loop engine with `max_turns=15` and micro-compact at 60% context
- MiniMax API provider (OpenAI-compatible, SSE streaming, function calling)
- 8 built-in tools: `file_read`, `file_write`, `file_edit`, `bash`, `grep`, `glob`, `web_search`, `todo`
- 4-level permission model (`allow` / `ask` / `deny` / `force_ask`)
- Dangerous command detection (`rm -rf`, `sudo`, `git push --force`, etc.)
- Forbidden path guard (`~/.ssh`, `~/.gnupg`, `/etc/shadow`, etc.)
- Sandbox mode for shared hosts
- Project context detection (`AGENTS.md`, `CLAUDE.md`, `README.md`)
- Language detection (Python / Node / Go / Rust / Java / Ruby)
- CLI with `--print`, `--sandbox`, `--auto-approve` modes
- 98 tests with 86% line coverage
