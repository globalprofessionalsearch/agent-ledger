"""
Markdown renderer for agent-ledger.
Converts DB query results into standardized markdown.
Pure Python stdlib.
"""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ledger.db import EXPORTS_DIR

ROLE_LABELS = {
    "user":        "👤 User",
    "assistant":   "🤖 Assistant",
    "tool_call":   "🔧 Tool Call",
    "tool_result": "📤 Tool Result",
    "system":      "⚙️  System",
}

SUBTYPE_LABELS = {
    "thinking":   "💭 Thinking",
    "summary":    "📋 Summary",
    "attachment": "🔗 Hook",
}


def _label(role: str, subtype: str) -> str:
    if subtype and subtype in SUBTYPE_LABELS:
        return SUBTYPE_LABELS[subtype]
    return ROLE_LABELS.get(role, role.title())


def _fmt_ts(ts: str) -> str:
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ts


def _to_utc_str(ts: str) -> str:
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def render_session_header(session) -> str:
    project  = session["project"] or "unknown"
    branch   = session["git_branch"] or "unknown"
    started  = _fmt_ts(session["started_at"]) if session["started_at"] else "unknown"
    ended    = _fmt_ts(session["ended_at"]) if session["ended_at"] else "in progress"
    cwd      = session["cwd"] or ""
    sid      = session["session_id"][:8]

    return "\n".join([
        f"## Session: {project} ({branch})",
        f"",
        f"- **ID:** `{sid}...`",
        f"- **Path:** `{cwd}`",
        f"- **Started:** {started}",
        f"- **Ended:** {ended}",
        f"",
    ])


def render_message(msg) -> str:
    role    = msg["role"]
    subtype = msg["subtype"]
    label   = _label(role, subtype)
    ts      = _fmt_ts(msg["timestamp"])
    content = (msg["content"] or "").strip()

    tool_info = ""
    if msg["tool_name"]:
        tool_info = f" `{msg['tool_name']}`"
    if msg["tool_use_id"]:
        tool_info += f" _(id: `{msg['tool_use_id'][:8]}...`)_"

    error_badge = " ⚠️ **ERROR**" if msg["is_error"] else ""

    return "\n".join([
        f"### {ts} — {label}{tool_info}{error_badge}",
        f"",
        content,
        f"",
    ])


def render_time_range(
    conn,
    start: str,
    end: str,
    project: Optional[str] = None,
    include_tool_calls: bool = True,
    include_tool_results: bool = True,
    include_system: bool = False,
) -> str:
    role_filter = ["user", "assistant"]
    if include_tool_calls:
        role_filter.append("tool_call")
    if include_tool_results:
        role_filter.append("tool_result")
    if include_system:
        role_filter.append("system")

    placeholders = ",".join("?" * len(role_filter))
    params = [_to_utc_str(start), _to_utc_str(end)] + role_filter

    project_clause = ""
    if project:
        project_clause = "AND s.project = ?"
        params.append(project)

    rows = conn.execute(f"""
        SELECT m.*, s.project, s.cwd, s.git_branch, s.started_at, s.ended_at
        FROM messages m
        JOIN sessions s ON m.session_id = s.session_id
        WHERE m.timestamp >= ?
          AND m.timestamp <= ?
          AND m.role IN ({placeholders})
          {project_clause}
        ORDER BY m.timestamp ASC, m.id ASC
    """, params).fetchall()

    if not rows:
        suffix = f" for project `{project}`" if project else ""
        return f"_No messages found between {start} and {end}{suffix}._\n"

    # Group by session preserving order
    sessions_seen = {}
    session_messages = {}
    for row in rows:
        sid = row["session_id"]
        if sid not in sessions_seen:
            sessions_seen[sid] = row
            session_messages[sid] = []
        session_messages[sid].append(row)

    parts = [
        f"# Agent Ledger — {_fmt_ts(start)} to {_fmt_ts(end)}",
        f"",
        f"_{len(rows)} messages across {len(sessions_seen)} session(s)_",
        f"",
    ]

    for sid, session_row in sessions_seen.items():
        parts.append(render_session_header(session_row))
        for msg in session_messages[sid]:
            parts.append(render_message(msg))
        parts.append("---")
        parts.append("")

    return "\n".join(parts)


def render_search_results(conn, query: str, rows: list) -> str:
    if not rows:
        return f"_No results found for: `{query}`_\n"

    parts = [
        f"# Agent Ledger Search: `{query}`",
        f"",
        f"_{len(rows)} result(s)_",
        f"",
    ]

    for row in rows:
        project = row["project"] or "unknown"
        branch  = row["git_branch"] or "unknown"
        ts      = _fmt_ts(row["timestamp"])
        label   = _label(row["role"], row["subtype"])
        content = (row["content"] or "")
        snippet = content[:500] + ("..." if len(content) > 500 else "")

        parts += [
            f"### {ts} — {label} | {project} ({branch})",
            f"",
            snippet,
            f"",
        ]

    return "\n".join(parts)


def default_export_path(start: str, end: str, project: Optional[str] = None) -> Path:
    """Generate a sensible default export filename."""
    try:
        dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
        date_str = dt.strftime("%Y-%m-%d_%H%M")
    except Exception:
        date_str = "export"
    suffix = f"_{project}" if project else ""
    return EXPORTS_DIR / f"{date_str}{suffix}.md"


def write_markdown(content: str, path: Path) -> str:
    path = Path(path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return f"Written {len(content)} characters to {path}"


def read_markdown(path: Path) -> str:
    path = Path(path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    return path.read_text(encoding="utf-8")
