"""
Activity map for agent-ledger.
Identifies where user activity is concentrated in a time range.
Pure Python stdlib.
"""

from datetime import datetime, timedelta, timezone

_DAY = 24 * 60 * 60
_WEEK = 7 * _DAY


def bucket_size_minutes(range_seconds: int) -> int:
    """Return bucket granularity in minutes for a given range length in seconds."""
    if range_seconds >= _WEEK:
        return 1440  # daily
    if range_seconds >= _DAY:
        return 60    # hourly
    if range_seconds >= 60 * 60:
        return 15
    return 5


def _parse_dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _fmt_dt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def build_buckets(conn, start: str, end: str, project, bucket_minutes: int) -> list:
    """Query user messages and group into fixed-width time buckets."""
    start_dt = _parse_dt(start)
    end_dt = _parse_dt(end)
    delta = timedelta(minutes=bucket_minutes)

    buckets = []
    t = start_dt
    while t < end_dt:
        bucket_end = min(t + delta, end_dt)
        buckets.append({"start": _fmt_dt(t), "end": _fmt_dt(bucket_end), "count": 0})
        t += delta

    project_clause = ""
    params = [start, end]
    if project:
        project_clause = "AND s.project = ?"
        params.append(project)

    rows = conn.execute(f"""
        SELECT m.timestamp FROM messages m
        JOIN sessions s ON m.session_id = s.session_id
        WHERE m.timestamp >= ? AND m.timestamp <= ?
          AND m.role = 'user' AND m.subtype = 'human' AND m.is_sidechain = 0
          {project_clause}
    """, params).fetchall()

    for row in rows:
        ts = _parse_dt(row["timestamp"])
        elapsed = (ts - start_dt).total_seconds()
        idx = int(elapsed // (bucket_minutes * 60))
        if 0 <= idx < len(buckets):
            buckets[idx]["count"] += 1

    return buckets
