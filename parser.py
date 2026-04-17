"""
Parser for Claude Code JSONL session files.
Converts raw JSONL events into structured message dicts ready for DB insertion.
Pure Python stdlib.
"""

import json
from datetime import datetime, timezone


def _ts_parts(ts: str) -> tuple:
    """Return (date_str YYYY-MM-DD, hour int) from ISO8601 timestamp."""
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d"), dt.hour
    except Exception:
        return "", 0


def _extract_text(content) -> str:
    """Flatten content to a plain string regardless of shape."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                btype = block.get("type", "")
                if btype == "text":
                    parts.append(block.get("text", ""))
                elif btype == "tool_result":
                    inner = block.get("content", "")
                    parts.append(f"[tool_result:{block.get('tool_use_id','')}] {_extract_text(inner)}")
                elif btype == "tool_use":
                    inp = json.dumps(block.get("input", {}), ensure_ascii=False)
                    parts.append(f"[tool_use:{block.get('name','')}] {inp}")
                elif btype == "thinking":
                    parts.append(f"[thinking] {block.get('thinking', '')}")
                else:
                    parts.append(json.dumps(block, ensure_ascii=False))
        return "\n".join(p for p in parts if p)
    if isinstance(content, dict):
        return json.dumps(content, ensure_ascii=False)
    return str(content) if content is not None else ""


def parse_line(raw: str) -> list:
    """
    Parse one JSONL line and return a list of message dicts (usually one,
    but assistant turns with multiple content blocks yield multiple rows).
    Returns None if the line should be skipped entirely.
    """
    raw = raw.strip()
    if not raw:
        return None
    try:
        event = json.loads(raw)
    except json.JSONDecodeError:
        return None

    etype = event.get("type")
    ts = event.get("timestamp", "")
    date, hour = _ts_parts(ts)
    session_id = event.get("sessionId", "")
    uuid = event.get("uuid", "")
    parent_uuid = event.get("parentUuid")
    is_sidechain = 1 if event.get("isSidechain") else 0
    agent_id = event.get("agentId")

    base = dict(
        session_id=session_id,
        timestamp=ts,
        date=date,
        hour=hour,
        uuid=uuid,
        parent_uuid=parent_uuid,
        is_sidechain=is_sidechain,
        agent_id=agent_id,
    )

    # ── session metadata ──────────────────────────────────────────────────────
    if etype == "permission-mode":
        return [{"_meta": "session", "session_id": session_id,
                 "permission_mode": event.get("permissionMode")}]

    # ── attachment / hook events ──────────────────────────────────────────────
    if etype == "attachment":
        att = event.get("attachment", {})
        att_type = att.get("type", "")
        hook_name = att.get("hookName", "")
        content_parts = []
        if att.get("stdout"):
            content_parts.append(f"stdout:\n{att['stdout']}")
        if att.get("stderr"):
            content_parts.append(f"stderr:\n{att['stderr']}")
        content = f"[hook:{hook_name} type:{att_type} exit:{att.get('exitCode')}]\n" + \
                  "\n".join(content_parts)
        return [{
            **base,
            "role": "system",
            "subtype": "attachment",
            "content": content,
            "tool_name": hook_name,
            "tool_use_id": att.get("toolUseID"),
            "is_error": 1 if att.get("exitCode", 0) not in (0, 127) else 0,
        }]

    # ── summary events ────────────────────────────────────────────────────────
    if etype == "summary":
        summary_text = event.get("summary", "")
        return [{
            **base,
            "role": "system",
            "subtype": "summary",
            "content": f"[session summary]\n{summary_text}",
            "tool_name": None,
            "tool_use_id": None,
            "is_error": 0,
        }]

    # ── user messages ─────────────────────────────────────────────────────────
    if etype == "user":
        msg = event.get("message", {})
        content_raw = msg.get("content", "")

        if isinstance(content_raw, list):
            rows = []
            for block in content_raw:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type", "")
                if btype == "tool_result":
                    inner = block.get("content", "")
                    text = _extract_text(inner)
                    rows.append({
                        **base,
                        "role": "tool_result",
                        "subtype": "tool_result",
                        "content": text,
                        "tool_name": None,
                        "tool_use_id": block.get("tool_use_id"),
                        "is_error": 1 if block.get("is_error") else 0,
                    })
                else:
                    text = _extract_text(block)
                    if text:
                        rows.append({
                            **base,
                            "role": "user",
                            "subtype": "human",
                            "content": text,
                            "tool_name": None,
                            "tool_use_id": None,
                            "is_error": 0,
                        })
            return rows if rows else None
        else:
            text = _extract_text(content_raw)
            if not text:
                return None
            return [{
                **base,
                "role": "user",
                "subtype": "human",
                "content": text,
                "tool_name": None,
                "tool_use_id": None,
                "is_error": 0,
            }]

    # ── assistant messages ────────────────────────────────────────────────────
    if etype == "assistant":
        msg = event.get("message", {})
        content_raw = msg.get("content", [])
        if isinstance(content_raw, str):
            content_raw = [{"type": "text", "text": content_raw}]

        rows = []
        for block in content_raw:
            if not isinstance(block, dict):
                continue
            btype = block.get("type", "")

            if btype == "text":
                text = block.get("text", "")
                if text.strip():
                    rows.append({
                        **base,
                        "role": "assistant",
                        "subtype": "text",
                        "content": text,
                        "tool_name": None,
                        "tool_use_id": None,
                        "is_error": 0,
                    })

            elif btype == "tool_use":
                inp = json.dumps(block.get("input", {}), ensure_ascii=False)
                rows.append({
                    **base,
                    "role": "tool_call",
                    "subtype": "tool_use",
                    "content": inp,
                    "tool_name": block.get("name"),
                    "tool_use_id": block.get("id"),
                    "is_error": 0,
                })

            elif btype == "thinking":
                thinking = block.get("thinking", "")
                if thinking.strip():
                    rows.append({
                        **base,
                        "role": "assistant",
                        "subtype": "thinking",
                        "content": f"[thinking]\n{thinking}",
                        "tool_name": None,
                        "tool_use_id": None,
                        "is_error": 0,
                    })

        return rows if rows else None

    # ── unknown — store raw ───────────────────────────────────────────────────
    return [{
        **base,
        "role": "system",
        "subtype": etype or "unknown",
        "content": json.dumps(event, ensure_ascii=False),
        "tool_name": None,
        "tool_use_id": None,
        "is_error": 0,
    }]


def session_info_from_event(event: dict) -> dict:
    """Extract session-level metadata from any event dict."""
    cwd = event.get("cwd", "")
    project = cwd.split("/")[-1] if cwd else ""
    return {
        "cwd": cwd,
        "project": project,
        "git_branch": event.get("gitBranch"),
        "entrypoint": event.get("entrypoint"),
        "version": event.get("version"),
    }
