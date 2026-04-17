# agent-ledger

Captures Claude Code JSONL session history into a searchable SQLite database, exposed via an MCP stdio server.

## Critical design decisions

**Pure stdlib.** No pip dependencies. Every file uses only Python builtins. Don't add third-party imports.

**Two directory roles:**
- `~/Documents/code/agent-ledger/` — source code
- `~/Documents/agent-ledger/` — runtime data (`memory.db`, `daemon.log`, `exports/`)

**FTS5 content table** (`db.py`): `messages_fts` uses `content='messages'` — FTS5 holds only the inverted index; text lives in `messages`. Three triggers (insert/update/delete) keep the index in sync. Don't remove the triggers or the FTS index silently goes stale.

**File cursor tracking** (`db.py: file_cursors`): The daemon stores `(last_line, last_mtime)` per JSONL file. On startup it resumes from the cursor — never re-ingests. The mtime check short-circuits reads when nothing changed.

**Session end detection** (`daemon.py: _maybe_mark_ended`): Claude Code writes no explicit close event. Sessions are marked ended when a file hasn't been modified for `--session-timeout` seconds (default 300s). `ended_at` is set to the file's mtime, not wall clock.

**MCP server is hand-rolled JSON-RPC 2.0** (`mcp_server.py`): Reads from stdin, writes to stdout — no MCP SDK. The `dispatch` dict routes `tools/call` by name. `notifications/initialized` is silently dropped (returns `None`, which the loop skips).

**Parser yields multiple rows per line** (`parser.py: parse_line`): One JSONL event can produce N DB rows (e.g., an assistant turn with text + tool_use blocks becomes two rows). Callers must handle a list, not a single dict.
