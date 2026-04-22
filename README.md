# agent-ledger

Captures all Claude Code session history into a searchable database, exposed to Claude via MCP tools. Ask Claude what you worked on, search past conversations, or export sessions as markdown.

**Pure Python stdlib. No pip installs required.**

## Quick Start

```bash
cd ~/Documents/code/agent-ledger
chmod +x install.sh
./install.sh
```

Follow the printed instructions to load the daemon and register the MCP server.

## What You Can Do

### Summarize a time range

Ask Claude to summarize any span of time -- a morning, a full day, a week. Claude first maps where activity was concentrated so it knows which windows deserve close reading and which can be skipped, then reads the relevant content at the right level of detail.

```
What did I work on today?
Give me an hour-by-hour summary of this morning
What were the main themes of last week's sessions?
```

### Search past conversations

Full-text search across everything you've discussed with Claude Code.

```
Search my memory for discussions about the registrar proxy
Find every time I asked about database migrations
What did I decide about the auth middleware?
```

### Export sessions as markdown

Render any time window as formatted markdown -- useful for writing up notes, sharing context, or pushing to Notion.

```
Export this morning's sessions to ~/Desktop/morning-notes.md
Write a markdown summary of yesterday afternoon
```

### Browse sessions and projects

```
List my recent sessions
What projects have I worked on?
Show me sessions from the agent-ledger project this week
```

## MCP Tools

| Tool | When Claude uses it |
|------|---------------------|
| `get_activity_map` | Before reading any large time range -- identifies where activity is concentrated and how carefully each window needs to be read |
| `write_markdown` | Renders a time window as markdown and writes it to disk for reading back |
| `render_markdown` | Renders a short, quiet time window as markdown directly in context |
| `read_markdown` | Reads a previously written markdown file |
| `search_memory` | Full-text search across all session history |
| `query_time_range` | Raw message retrieval for programmatic inspection |
| `list_sessions` | Lists recent sessions, optionally filtered by project |
| `list_projects` | Lists all projects with recorded history |

## Daemon

The background daemon watches your Claude Code session files and keeps the database up to date.

```bash
python3 daemon.py [--interval SECONDS] [--session-timeout SECONDS] [--debug]
```

- **`--interval`** -- how often to scan for new activity (default: 30s)
- **`--session-timeout`** -- inactivity before a session is marked ended (default: 300s)
- **`--debug`** -- verbose logging

Safe to stop and restart at any time -- the daemon tracks where it left off and never re-processes history.

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

Or use the CLI:

```bash
claude mcp add agent-ledger -- python3 /path/to/agent-ledger/mcp_server.py
```
