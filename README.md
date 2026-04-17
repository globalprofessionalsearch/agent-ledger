# agent-ledger

Captures all Claude Code CLI session history into a searchable SQLite database with full-text search and markdown export.

**Pure Python stdlib. No pip installs required.**

## Structure

```
~/Documents/code/agent-ledger/   ← code
    db.py                         schema, connection helpers
    parser.py                     JSONL → structured rows
    daemon.py                     polls ~/.claude/projects/, ingests new lines
    renderer.py                   renders DB rows as markdown
    mcp_server.py                 MCP stdio server
    install.sh                    autostart setup

~/Documents/agent-ledger/        ← data
    memory.db                     SQLite database
    daemon.log                    daemon output
    exports/markdown/             default markdown export location
```

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
Write a markdown export of this morning's jeenius-cli sessions to ~/Desktop/morning.md
```

## MCP Registration

Add to `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "agent-ledger": {
      "command": "python3",
      "args": ["/Users/joe/Documents/code/agent-ledger/mcp_server.py"]
    }
  }
}
```

## Direct DB Queries

```bash
# Full-text search
sqlite3 ~/Documents/agent-ledger/memory.db \
  "SELECT timestamp, role, content
   FROM messages_fts
   JOIN messages ON messages_fts.rowid = messages.id
   WHERE messages_fts MATCH 'registrar proxy'
   LIMIT 10;"

# All messages today
sqlite3 ~/Documents/agent-ledger/memory.db \
  "SELECT timestamp, role, substr(content,1,200)
   FROM messages
   WHERE date = date('now')
   ORDER BY timestamp;"

# Sessions for a project
sqlite3 ~/Documents/agent-ledger/memory.db \
  "SELECT session_id, started_at, ended_at, git_branch
   FROM sessions
   WHERE project = 'jeenius-cli'
   ORDER BY started_at DESC;"
```
