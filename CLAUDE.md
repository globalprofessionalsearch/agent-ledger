# agent-ledger

Captures Claude Code JSONL session history into a searchable SQLite database, exposed via an MCP stdio server.

## Critical design decisions

**Pure stdlib.** No pip dependencies. Every file uses only Python builtins. Don't add third-party imports.

**Two directory roles:** source code lives separately from runtime data (`memory.db`, `daemon.log`, `exports/`). This is intentional — don't collapse them.

**FTS5 content table:** `messages_fts` uses a content table pointing at `messages` — FTS5 holds only the inverted index; text lives in the main table. Three triggers (insert/update/delete) keep the index in sync. Don't remove the triggers or the FTS index silently goes stale.

**File cursor tracking:** The daemon stores `(last_line, last_mtime)` per JSONL file. On startup it resumes from the cursor — never re-ingests. The mtime check short-circuits reads when nothing changed.

**Session end detection:** Claude Code writes no explicit close event. Sessions are marked ended when a file hasn't been modified for `--session-timeout` seconds (default 300s). `ended_at` is set to the file's mtime, not wall clock.

**MCP server is hand-rolled JSON-RPC 2.0:** Reads from stdin, writes to stdout — no MCP SDK. Notifications (e.g. `notifications/initialized`) return `None` and are silently dropped by the write loop.

**Parser yields multiple rows per line:** One JSONL event can produce N DB rows (e.g., an assistant turn with text + tool_use blocks becomes two rows). Callers must handle a list, not a single dict.
