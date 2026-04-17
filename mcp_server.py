#!/usr/bin/env python3
"""
agent-ledger MCP server
Implements MCP stdio protocol (JSON-RPC 2.0) over stdin/stdout.
Pure Python stdlib — no MCP SDK required.

Tools:
  search_memory        — FTS5 full-text search
  query_time_range     — raw time-range retrieval
  render_markdown      — render time range as markdown string
  write_markdown       — render + write to disk
  read_markdown        — read markdown file from disk
  list_sessions        — list recent sessions
  list_projects        — list all known projects
"""

import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from db import DB_PATH, initialize, get_connection
from renderer import (
    render_time_range, render_search_results,
    write_markdown as _write_markdown,
    read_markdown as _read_markdown,
    default_export_path,
    EXPORTS_DIR,
)


def _rows(result) -> list:
    return [dict(r) for r in result]


# ── tools ─────────────────────────────────────────────────────────────────────

def search_memory(conn, p: dict) -> dict:
    query = p.get("query", "").strip()
    limit = min(int(p.get("limit", 20)), 100)
    if not query:
        return {"error": "query is required"}

    rows = conn.execute("""
        SELECT m.id, m.session_id, m.role, m.subtype, m.content,
               m.tool_name, m.tool_use_id, m.is_error,
               m.timestamp, m.date, m.hour,
               s.project, s.cwd, s.git_branch,
               messages_fts.rank
        FROM messages_fts
        JOIN messages m ON messages_fts.rowid = m.id
        JOIN sessions s ON m.session_id = s.session_id
        WHERE messages_fts MATCH ?
        ORDER BY messages_fts.rank
        LIMIT ?
    """, [query, limit]).fetchall()

    return {
        "count": len(rows),
        "query": query,
        "markdown": render_search_results(conn, query, rows),
        "results": _rows(rows),
    }


def query_time_range(conn, p: dict) -> dict:
    start   = p.get("start", "").strip()
    end     = p.get("end", "").strip()
    project = p.get("project", "").strip() or None
    limit   = min(int(p.get("limit", 200)), 1000)

    if not start or not end:
        return {"error": "start and end are required (ISO8601)"}

    params = [start, end]
    project_clause = ""
    if project:
        project_clause = "AND s.project = ?"
        params.append(project)
    params.append(limit)

    rows = conn.execute(f"""
        SELECT m.*, s.project, s.cwd, s.git_branch, s.started_at, s.ended_at
        FROM messages m
        JOIN sessions s ON m.session_id = s.session_id
        WHERE m.timestamp >= ? AND m.timestamp <= ?
          {project_clause}
        ORDER BY m.timestamp ASC, m.id ASC
        LIMIT ?
    """, params).fetchall()

    return {"count": len(rows), "start": start, "end": end,
            "project": project, "results": _rows(rows)}


def render_markdown(conn, p: dict) -> dict:
    start   = p.get("start", "").strip()
    end     = p.get("end", "").strip()
    project = p.get("project", "").strip() or None
    if not start or not end:
        return {"error": "start and end are required (ISO8601)"}

    md = render_time_range(conn, start, end, project,
                           include_tool_calls=bool(p.get("include_tools", True)),
                           include_tool_results=bool(p.get("include_tools", True)),
                           include_system=bool(p.get("include_system", False)))
    return {"markdown": md, "length": len(md)}


def write_markdown_tool(conn, p: dict) -> dict:
    start   = p.get("start", "").strip()
    end     = p.get("end", "").strip()
    project = p.get("project", "").strip() or None
    path    = p.get("path", "").strip() or None

    if not start or not end:
        return {"error": "start and end are required (ISO8601)"}

    # Default path if not provided
    if not path:
        path = str(default_export_path(start, end, project))

    md = render_time_range(conn, start, end, project,
                           include_tool_calls=bool(p.get("include_tools", True)),
                           include_tool_results=bool(p.get("include_tools", True)),
                           include_system=bool(p.get("include_system", False)))
    result = _write_markdown(md, Path(path))
    return {"result": result, "path": str(path), "length": len(md)}


def read_markdown_tool(p: dict) -> dict:
    path = p.get("path", "").strip()
    if not path:
        return {"error": "path is required"}
    try:
        content = _read_markdown(Path(path))
        return {"content": content, "length": len(content), "path": path}
    except FileNotFoundError as e:
        return {"error": str(e)}


def list_sessions(conn, p: dict) -> dict:
    project = p.get("project", "").strip() or None
    limit   = min(int(p.get("limit", 20)), 100)

    params = []
    project_clause = ""
    if project:
        project_clause = "WHERE project = ?"
        params.append(project)
    params.append(limit)

    rows = conn.execute(f"""
        SELECT session_id, project, cwd, git_branch, entrypoint,
               version, started_at, ended_at, last_seen_at
        FROM sessions
        {project_clause}
        ORDER BY started_at DESC
        LIMIT ?
    """, params).fetchall()

    return {"count": len(rows), "sessions": _rows(rows)}


def list_projects(conn, p: dict) -> dict:
    rows = conn.execute("""
        SELECT project, cwd,
               COUNT(DISTINCT session_id) as session_count,
               MIN(started_at) as first_seen,
               MAX(last_seen_at) as last_seen
        FROM sessions
        WHERE project IS NOT NULL AND project != ''
        GROUP BY project, cwd
        ORDER BY last_seen DESC
    """).fetchall()
    return {"count": len(rows), "projects": _rows(rows)}


# ── tool manifest ─────────────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "search_memory",
        "description": (
            "Full-text search across all Claude Code session history. "
            "Returns ranked results. Supports FTS5 syntax: AND, OR, NOT, \"phrase quotes\". "
            "Use to find specific examples, decisions, errors, or topics from past sessions."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "FTS5 search query"},
                "limit": {"type": "integer", "default": 20, "description": "Max results (max 100)"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "query_time_range",
        "description": "Retrieve raw messages within a time range. Returns structured JSON.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "start":   {"type": "string", "description": "ISO8601 start time"},
                "end":     {"type": "string", "description": "ISO8601 end time"},
                "project": {"type": "string", "description": "Filter by project name (optional)"},
                "limit":   {"type": "integer", "default": 200}
            },
            "required": ["start", "end"]
        }
    },
    {
        "name": "render_markdown",
        "description": (
            "Render session history as formatted markdown for a time window. "
            "Use for queries like 'show me what happened around 9am today'."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "start":          {"type": "string", "description": "ISO8601 start time"},
                "end":            {"type": "string", "description": "ISO8601 end time"},
                "project":        {"type": "string", "description": "Filter by project (optional)"},
                "include_tools":  {"type": "boolean", "default": True},
                "include_system": {"type": "boolean", "default": False}
            },
            "required": ["start", "end"]
        }
    },
    {
        "name": "write_markdown",
        "description": (
            "Render session history as markdown and write to disk. "
            "If path is omitted, writes to the default exports directory. "
            "Use for exporting sessions for sharing or pushing to Notion."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "start":          {"type": "string", "description": "ISO8601 start time"},
                "end":            {"type": "string", "description": "ISO8601 end time"},
                "path":           {"type": "string", "description": f"Output path (default: {EXPORTS_DIR}/<date>.md)"},
                "project":        {"type": "string", "description": "Filter by project (optional)"},
                "include_tools":  {"type": "boolean", "default": True},
                "include_system": {"type": "boolean", "default": False}
            },
            "required": ["start", "end"]
        }
    },
    {
        "name": "read_markdown",
        "description": "Read a markdown file from disk and return its contents.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to read"}
            },
            "required": ["path"]
        }
    },
    {
        "name": "list_sessions",
        "description": "List recent Claude Code sessions, optionally filtered by project.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {"type": "string"},
                "limit":   {"type": "integer", "default": 20}
            }
        }
    },
    {
        "name": "list_projects",
        "description": "List all projects that have session history in the ledger.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
]


# ── JSON-RPC handler ──────────────────────────────────────────────────────────

def handle(conn, req: dict):
    method = req.get("method", "")
    rid    = req.get("id")
    params = req.get("params", {})

    def ok(result):
        return {"jsonrpc": "2.0", "id": rid, "result": result}

    def err(code, msg):
        return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": msg}}

    try:
        if method == "initialize":
            return ok({
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "agent-ledger", "version": "1.0.0"}
            })

        if method == "tools/list":
            return ok({"tools": TOOLS})

        if method == "tools/call":
            name   = params.get("name", "")
            args   = params.get("arguments", {})

            dispatch = {
                "search_memory":    lambda: search_memory(conn, args),
                "query_time_range": lambda: query_time_range(conn, args),
                "render_markdown":  lambda: render_markdown(conn, args),
                "write_markdown":   lambda: write_markdown_tool(conn, args),
                "read_markdown":    lambda: read_markdown_tool(args),
                "list_sessions":    lambda: list_sessions(conn, args),
                "list_projects":    lambda: list_projects(conn, args),
            }

            if name not in dispatch:
                return err(-32601, f"Unknown tool: {name}")

            result = dispatch[name]()

            if "error" in result:
                return err(-32602, result["error"])

            return ok({"content": [{"type": "text", "text": json.dumps(result, indent=2)}]})

        if method in ("notifications/initialized",):
            return None  # no response for notifications

        return err(-32601, f"Method not found: {method}")

    except Exception as e:
        return err(-32603, f"Internal error: {e}\n{traceback.format_exc()}")


# ── entry point ───────────────────────────────────────────────────────────────

def main():
    initialize()
    conn = get_connection()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue

        response = handle(conn, req)
        if response is not None:
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()

    conn.close()


if __name__ == "__main__":
    main()
