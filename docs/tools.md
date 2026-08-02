# Tools Reference

`minimax-agent` includes eight built-in tools for file manipulation, shell execution, search, and task management.

## Overview

| Tool | Description | Default Permission |
|------|-------------|-------------------|
| `file_read` | Read file contents | `allow` |
| `file_write` | Write to file | `ask` |
| `file_edit` | Edit file (search/replace) | `ask` |
| `bash` | Execute shell command | `ask` |
| `grep` | Search file contents | `allow` |
| `glob` | Find files by pattern | `allow` |
| `web_search` | DuckDuckGo web search | `allow` |
| `todo` | Manage session task list | `allow` |

## Permission Levels

- **`allow`**: Tool runs without prompting the user
- **`ask`**: Prompt the user the first time per session, remember the answer
- **`deny`**: Tool is rejected with an error
- **`force_ask`**: Tool always prompts the user, no memory of past answers

## Tool Details

### file_read

Read a slice of a file from disk.

**Parameters:**
- `path` (string, required): Path to the file to read
- `offset` (integer, optional): 1-indexed starting line number
- `limit` (integer, optional): Maximum number of lines to return

**Returns:** File contents as string, with header if offset is set.

**Example:**
```json
{
  "path": "src/main.py",
  "offset": 10,
  "limit": 20
}
```

**Notes:**
- Large files are truncated at 200,000 characters
- Forbidden paths (`~/.ssh`, `~/.gnupg`, etc.) raise `PermissionError`

---

### file_write

Write content to a file, creating parent directories if needed.

**Parameters:**
- `path` (string, required): Destination file path
- `content` (string, required): Full file content to write

**Returns:** Confirmation message with byte count.

**Example:**
```json
{
  "path": "output.txt",
  "content": "Hello, world!"
}
```

**Notes:**
- Overwrites existing files
- Creates parent directories automatically
- Writes as UTF-8

---

### file_edit

Exact-string replace inside a file.

**Parameters:**
- `path` (string, required): File to edit
- `old_string` (string, required): Exact substring to replace
- `new_string` (string, required): Replacement string
- `replace_all` (boolean, optional, default: false): Replace all occurrences

**Returns:** Summary with replacement count.

**Example:**
```json
{
  "path": "config.py",
  "old_string": "DEBUG = True",
  "new_string": "DEBUG = False"
}
```

**Notes:**
- Fails if `old_string` is empty, not found, or ambiguous (multiple matches without `replace_all`)

---

### bash

Execute a shell command, capture output, enforce timeout.

**Parameters:**
- `command` (string, required): Shell command to execute
- `timeout` (integer, optional, default: 60): Timeout in seconds (max 600)

**Returns:** Combined stdout+stderr. Non-zero exit codes append `[exit code N]`.

**Example:**
```json
{
  "command": "python -m pytest tests/ -v",
  "timeout": 120
}
```

**Notes:**
- Dangerous commands (`rm -rf /`, `sudo`, `git push --force`, etc.) are refused
- Output truncated at 50,000 bytes
- Timeout capped at 600 seconds (10 minutes)

---

### grep

Search file contents using ripgrep when available, else pure Python fallback.

**Parameters:**
- `pattern` (string, required): Regex pattern to search for
- `path` (string, optional, default: "."): File or directory to search
- `include` (string, optional): Glob filter (e.g., `*.py`)
- `case_insensitive` (boolean, optional, default: false): Case-insensitive search
- `max_results` (integer, optional, default: 200): Max matches to return

**Returns:** `path:lineno:line` formatted list.

**Example:**
```json
{
  "pattern": "def\\s+\\w+",
  "path": "src/",
  "include": "*.py",
  "max_results": 50
}
```

**Notes:**
- Uses ripgrep if available, falls back to pure Python
- Results truncated at `max_results`

---

### glob

Find files by glob pattern.

**Parameters:**
- `pattern` (string, required): Glob pattern (e.g., `**/*.py`)
- `path` (string, optional, default: "."): Root directory to search
- `max_results` (integer, optional, default: 200): Max matches

**Returns:** Newline-separated list of matched paths.

**Example:**
```json
{
  "pattern": "**/*.test.js",
  "path": "tests/"
}
```

---

### web_search

Best-effort web search via DuckDuckGo HTML (no API key required).

**Parameters:**
- `query` (string, required): Search query
- `max_results` (integer, optional, default: 5): Number of results (1-8)

**Returns:** Formatted list of `title — url` lines with snippets.

**Example:**
```json
{
  "query": "Python asyncio tutorial",
  "max_results": 3
}
```

**Notes:**
- Uses DuckDuckGo HTML scraping (no API key needed)
- For production use, consider swapping with a real search API
- Results limited to 8

---

### todo

Manage a session task list (in-memory, lives for duration of agent loop).

**Parameters:**
- `action` (string, required): One of `add`, `update`, `remove`, `list`
- `id` (integer, optional): Task id (for update/remove)
- `content` (string, optional): Task text (for add/update)
- `status` (string, optional): Task status (for add/update)

**Returns:** Status message or task list.

**Actions:**

#### add
```json
{
  "action": "add",
  "content": "Implement user authentication",
  "status": "pending"
}
```

#### update
```json
{
  "action": "update",
  "id": 1,
  "status": "in_progress"
}
```

#### remove
```json
{
  "action": "remove",
  "id": 1
}
```

#### list
```json
{
  "action": "list"
}
```

**Notes:**
- State is in-memory only, reset between CLI runs
- Status values: `pending`, `in_progress`, `done`, `completed`

## Adding New Tools

See [CONTRIBUTING.md](../CONTRIBUTING.md#adding-new-tools) for instructions on adding custom tools.

## Security

All tools are subject to:
1. **Permission checks** (see permission levels above)
2. **Dangerous command detection** (for `bash`)
3. **Forbidden path guard** (for `file_read`, `file_write`, `file_edit`)

See [security.md](security.md) for details.
