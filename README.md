# agent-ledger

Captures all Claude Code CLI session history into a searchable SQLite database with full-text search and markdown export.

**Pure Python stdlib. No pip installs required.**

## Quick Start

```bash
cd ~/Documents/code/agent-ledger
chmod +x install.sh
./install.sh
```

Follow the printed instructions to load the daemon and register the MCP server.

## Daemon

```bash
python3 daemon.py [--interval SECONDS] [--session-timeout SECONDS] [--debug]
```

- **`--interval`** — scan frequency (default: 30s)
- **`--session-timeout`** — inactivity before session marked ended (default: 300s)
- **`--debug`** — verbose logging

The daemon creates all required directories on startup. Safe to stop/restart at any time — it tracks a cursor per file so it never re-processes lines.

## MCP Tools

| Tool | Description |
|------|-------------|
| `search_memory` | FTS5 full-text search across all messages |
| `query_time_range` | Raw message retrieval for a time window |
| `render_markdown` | Render a time window as markdown |
| `write_markdown` | Render and write markdown to disk |
| `read_markdown` | Read a markdown file from disk |
| `list_sessions` | List recent sessions (optionally by project) |
| `list_projects` | List all known projects |

### Example prompts in Claude Code

```
Search my memory for discussions about the registrar proxy
```
```
Give me all conversation history for today around 9am as markdown
```
```
Write a markdown export of this morning's sessions to ~/Desktop/morning.md
```

## MCP Registration

Add to `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "agent-ledger": {
      "command": "python3",
      "args": ["/path/to/agent-ledger/mcp_server.py"]
    }
  }
}
```
