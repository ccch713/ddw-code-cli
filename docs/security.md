# Security Model

`minimax-agent` implements a multi-layered security model to prevent accidental or malicious damage to the host system.

## Overview

The security model has four layers:

1. **Permission Levels**: Control whether tools run automatically or require user confirmation
2. **Dangerous Command Detection**: Pattern matching to block destructive shell commands
3. **Forbidden Path Guard**: Prevents reading sensitive system files
4. **Sandbox Mode**: Forces confirmation for all mutating operations

## Layer 1: Permission Levels

Each tool has a default permission level that determines how it behaves:

| Level | Behavior |
|-------|----------|
| `allow` | Tool runs without prompting the user |
| `ask` | Prompt the user the first time per session, remember the answer |
| `deny` | Tool is rejected with an error |
| `force_ask` | Tool always prompts the user, no memory of past answers |

### Default Policies

| Tool | Default | Rationale |
|------|---------|-----------|
| `file_read` | `allow` | Read-only, no side effects |
| `file_write` | `ask` | Mutates filesystem |
| `file_edit` | `ask` | Mutates filesystem |
| `bash` | `ask` | Can execute arbitrary commands |
| `grep` | `allow` | Read-only, no side effects |
| `glob` | `allow` | Read-only, no side effects |
| `web_search` | `allow` | External API call, no local side effects |
| `todo` | `allow` | In-memory only, no persistence |

### Permission Flow

```
Tool Call Request
       │
       ▼
┌──────────────┐
│ Check Policy │
└──────────────┘
       │
       ├─ allow ──────▶ Execute
       ├─ deny ───────▶ Reject with error
       ├─ ask ────────▶ Check session memory
       │                      │
       │                      ├─ approved ──▶ Execute
       │                      └─ not yet ──▶ Prompt user
       │                                       │
       │                                       ├─ yes ─▶ Remember + Execute
       │                                       └─ no ──▶ Reject
       └─ force_ask ──▶ Prompt user (always)
```

## Layer 2: Dangerous Command Detection

The `bash` tool inspects commands against known destructive patterns before execution.

### Blocked Patterns

| Pattern | Example | Risk |
|---------|---------|------|
| `rm -rf /` | `rm -rf /` | Deletes root filesystem |
| `rm -rf` with glob | `rm -rf *` | Deletes everything in current directory |
| Force push | `git push --force` | Overwrites remote history |
| Hard reset | `git reset --hard` | Discards local changes |
| `sudo` | `sudo rm -rf /` | Privilege escalation |
| Disk wipe | `dd if=/dev/zero of=/dev/sda` | Destroys disk |
| Fork bomb | `:(){ :|:& };:` | Crashes system |
| Filesystem format | `mkfs.ext4 /dev/sda` | Destroys disk |
| Shutdown | `shutdown -h now` | System disruption |
| Curl pipe to shell | `curl ... \| sh` | Remote code execution |
| Raw disk write | `> /dev/sda` | Disk corruption |
| Remote eval | `eval $(curl ...)` | Remote code execution |

### Safe Commands

These commands bypass the heuristic (always allowed):

- `ls`, `pwd`, `echo`, `cat`, `head`, `tail`, `grep`, `rg`, `find`, `wc`
- `git status`, `git log`, `git diff`, `git show`, `git branch`

### Bypassing the Check

If a command is incorrectly flagged as dangerous:

1. Run it manually outside the agent
2. Or modify `minimax_agent/security/danger_check.py` to add an exception

## Layer 3: Forbidden Path Guard

File operations (`file_read`, `file_write`, `file_edit`) are checked against sensitive paths.

### Protected Paths

| Path | Why |
|------|-----|
| `~/.ssh` | SSH private keys |
| `~/.gnupg` | GPG private keys |
| `~/.aws/credentials` | AWS access keys |
| `~/.config/git` | Git credentials |
| `/etc/shadow` | Password hashes |
| `/etc/passwd` | User information |
| `/etc/sudoers` | Sudo configuration |

### How It Works

1. Resolve the path to absolute form (expand `~`, resolve symlinks)
2. Check if the resolved path starts with any forbidden prefix
3. Reject with `PermissionError` if matched

### Adding Custom Forbidden Paths

Edit `FORBIDDEN_PATH_PREFIXES` in `minimax_agent/config.py`:

```python
FORBIDDEN_PATH_PREFIXES: tuple[str, ...] = (
    str(Path.home() / ".ssh"),
    str(Path.home() / ".gnupg"),
    # Add your custom paths here
    "/etc/kubernetes",
    str(Path.home() / ".kube"),
)
```

## Layer 4: Sandbox Mode

Sandbox mode is the most restrictive setting, designed for shared hosts or untrusted environments.

### What Sandbox Mode Does

- Flips all mutating tools (`file_write`, `file_edit`, `bash`) to `force_ask`
- Every mutation requires explicit user confirmation
- No memory of past approvals (each call prompts)

### Enabling Sandbox Mode

```bash
# Via CLI flag
minimax-agent --sandbox "your prompt"

# Via environment variable
export MINIMAX_SANDBOX=1
minimax-agent "your prompt"
```

### When to Use Sandbox Mode

- Running on a shared server
- Testing the agent with untrusted prompts
- Learning how the agent works
- Any situation where you want maximum caution

## API Key Security

### Token Plan Keys

- Keys start with `sk-cp-`
- Required for authentication
- Never logged or displayed in output
- Loaded from: `MINIMAX_API_KEY` or `MINIMAX_TOKEN` env vars

### Best Practices

1. **Never commit API keys** to version control
2. **Use environment variables** or a `.env` file (gitignored)
3. **Rotate keys** if compromised
4. **Use different keys** for development and production

## Threat Model

### What We Protect Against

- **Accidental damage**: Destructive commands, file deletions
- **Credential leakage**: Reading SSH keys, API keys
- **Privilege escalation**: `sudo` commands
- **Remote code execution**: `curl | sh`, `eval`

### What We Don't Protect Against

- **Determined attacker with shell access**: The agent runs with user privileges
- **Network-based attacks**: The agent makes outbound HTTP requests
- **Side-channel attacks**: Timing, power analysis, etc.
- **Supply chain attacks**: Malicious dependencies

## Reporting Security Issues

If you discover a security vulnerability, please:

1. **Do NOT** open a public GitHub issue
2. Email security concerns to: [INSERT SECURITY EMAIL]
3. Include:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Suggested fix (if any)

## Security Checklist for Contributors

When adding new tools or modifying security:

- [ ] Does the tool need file access? Add path guard checks
- [ ] Does the tool execute commands? Add dangerous command detection
- [ ] Is the tool read-only? Set default permission to `allow`
- [ ] Does the tool mutate state? Set default permission to `ask`
- [ ] Are there edge cases that bypass checks? Add tests
- [ ] Is the security documentation updated?

## Further Reading

- [CONTRIBUTING.md](../CONTRIBUTING.md) - Development guidelines
- [tools.md](tools.md) - Tool reference with permission defaults
- [providers.md](providers.md) - Provider security considerations
