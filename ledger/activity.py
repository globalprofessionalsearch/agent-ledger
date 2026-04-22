"""
Activity map for agent-ledger.
Identifies where user activity is concentrated in a time range.
Pure Python stdlib.
"""

from datetime import datetime, timedelta

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

    # project_clause is a hardcoded literal, not user input — no injection risk
    project_clause = "AND s.project = ?" if project else ""
    params = [start, end]
    if project:
        params.append(project)

    rows = conn.execute(f"""
        SELECT m.timestamp FROM messages m
        JOIN sessions s ON m.session_id = s.session_id
        WHERE m.timestamp >= ? AND m.timestamp < ?
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


def _find_natural_breaks(sorted_counts: list) -> list:
    """Find up to 2 class break points using natural gap detection.

    Returns a sorted list of break values (upper bounds of lower classes).
    A break at value V means: class boundary between V and V+1.
    """
    if len(sorted_counts) < 2:
        return []

    counts = sorted(sorted_counts)
    gaps = [counts[i + 1] - counts[i] for i in range(len(counts) - 1)]
    median_gap = sorted(gaps)[len(gaps) // 2]

    significant = sorted(
        [(gaps[i], counts[i]) for i in range(len(gaps)) if gaps[i] > median_gap],
        reverse=True,
    )[:2]

    return sorted(v for _, v in significant)


def _classify(count: int, breaks: list) -> str:
    """Assign a class label to a bucket count given a list of break points."""
    if count == 0:
        return "quiet"
    if not breaks:
        return "active"
    if count <= breaks[0]:
        return "quiet"
    if len(breaks) == 1 or count <= breaks[1]:
        return "active"
    return "dense"


def _build_classes(breaks: list, min_nonzero: int, max_nonzero: int) -> dict:
    """Build the classes boundary dict for the response."""
    if not breaks:
        return {"active": {"min_count": min_nonzero, "max_count": max_nonzero}}
    if len(breaks) == 1:
        return {
            "quiet":  {"max_count": breaks[0]},
            "active": {"min_count": breaks[0] + 1, "max_count": max_nonzero},
        }
    return {
        "quiet":  {"max_count": breaks[0]},
        "active": {"min_count": breaks[0] + 1, "max_count": breaks[1]},
        "dense":  {"min_count": breaks[1] + 1},
    }


_LEAF_BUCKET_MINUTES = 5


def _suggested_calls(bucket: dict, bucket_minutes: int) -> list:
    """Return structured suggested next-tool calls for a classified bucket."""
    cls = bucket["class"]
    if cls == "quiet":
        return []
    if cls not in ("active", "dense"):
        raise ValueError(f"Unknown bucket class: {cls!r}")

    at_leaf = bucket_minutes <= _LEAF_BUCKET_MINUTES

    if cls == "dense" and not at_leaf:
        return [{
            "tool": "get_activity_map",
            "reason": "Window is dense -- subdivide before reading to avoid missing nuance",
            "args": {"start": bucket["start"], "end": bucket["end"]},
        }]

    reason = (
        "Active window -- ready to read at this granularity"
        if cls == "active"
        else "Dense window at minimum granularity -- read directly"
    )
    return [{
        "tool": "write_markdown",
        "reason": reason,
        "args": {"start": bucket["start"], "end": bucket["end"]},
    }]


def activity_map(conn, params: dict) -> dict:
    """Main entry point for the get_activity_map MCP tool."""
    start   = params.get("start", "").strip()
    end     = params.get("end", "").strip()
    project = (params.get("project") or "").strip() or None

    start_dt = _parse_dt(start)
    end_dt   = _parse_dt(end)
    range_seconds = int((end_dt - start_dt).total_seconds())
    bm = bucket_size_minutes(range_seconds)

    buckets = build_buckets(conn, start, end, project, bm)
    total = sum(b["count"] for b in buckets)

    if total == 0:
        return {
            "bucket_size_minutes": bm,
            "total_user_messages": 0,
            "interpretation": "No user activity found in this range.",
            "classes": {},
            "histogram": [{**b, "class": "quiet"} for b in buckets],
            "hot_windows": [],
        }

    nonzero_counts = sorted(b["count"] for b in buckets if b["count"] > 0)
    breaks = _find_natural_breaks(nonzero_counts)
    classes = _build_classes(breaks, min_nonzero=nonzero_counts[0], max_nonzero=nonzero_counts[-1])

    classified = []
    for b in buckets:
        cls = _classify(b["count"], breaks)
        classified.append({**b, "class": cls})

    hot_windows = []
    for b in classified:
        if b["class"] == "quiet":
            continue
        calls = _suggested_calls(b, bm)
        hot_windows.append({**b, "suggested_calls": calls})

    hot_windows.sort(key=lambda w: w["count"], reverse=True)

    n_dense  = sum(1 for w in hot_windows if w["class"] == "dense")
    n_active = sum(1 for w in hot_windows if w["class"] == "active")
    n_quiet  = sum(1 for b in classified  if b["class"] == "quiet")
    k = len(breaks) + 1

    interpretation = (
        f"{total} user message(s) across {len(buckets)} bucket(s) "
        f"({bm}-minute resolution). "
        f"Natural gap detection found {k} tier(s). "
    )
    if n_dense:
        interpretation += (
            f"{n_dense} dense window(s) warrant subdivision before reading. "
        )
    if n_active:
        interpretation += f"{n_active} active window(s) are ready to read directly. "
    if n_quiet:
        interpretation += f"{n_quiet} quiet bucket(s) can be skipped."

    return {
        "bucket_size_minutes": bm,
        "total_user_messages": total,
        "interpretation": interpretation.strip(),
        "classes": classes,
        "histogram": classified,
        "hot_windows": hot_windows,
    }
