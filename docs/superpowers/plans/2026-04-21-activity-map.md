# Activity Map Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `get_activity_map` MCP tool that identifies where user activity is concentrated in a time range, classifies windows as `quiet`/`active`/`dense`, and annotates each hot window with structured `suggested_calls` guiding Claude toward the correct next tool.

**Architecture:** A new `ledger/` package encapsulates all core logic (db, parser, renderer, activity). Entry points (`daemon.py`, `mcp_server.py`) import from `ledger.*`. The activity module implements scale-aware bucketing + natural-break classification + suggested-call generation as pure functions, all tested against in-memory SQLite.

**Tech Stack:** Python 3, stdlib only (`sqlite3`, `datetime`, `json`), pytest for tests.

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Create | `ledger/__init__.py` | Package marker (empty) |
| Move | `ledger/db.py` | Schema, connection, upsert helpers |
| Move | `ledger/parser.py` | JSONL → message dicts |
| Move | `ledger/renderer.py` | Markdown formatting |
| Create | `ledger/activity.py` | Bucket builder, Jenks, classifier, suggested-call generator, `activity_map()` |
| Delete | `db.py` | Replaced by `ledger/db.py` |
| Delete | `parser.py` | Replaced by `ledger/parser.py` |
| Delete | `renderer.py` | Replaced by `ledger/renderer.py` |
| Modify | `daemon.py` | Update imports to `ledger.*`, remove `sys.path.insert` |
| Modify | `mcp_server.py` | Update imports, add `get_activity_map` tool + handler, update 3 tool descriptions |
| Create | `tests/__init__.py` | Test package marker (empty) |
| Create | `tests/conftest.py` | Shared pytest fixture: in-memory SQLite DB with schema |
| Create | `tests/test_activity.py` | All tests for `ledger/activity.py` |

---

## Task 1: Feature Branch + Package Restructure

**Files:**
- Create: `ledger/__init__.py`
- Move to: `ledger/db.py`, `ledger/parser.py`, `ledger/renderer.py`
- Delete: `db.py`, `parser.py`, `renderer.py`
- Modify: `daemon.py`, `mcp_server.py`

- [ ] **Step 1: Create the feature branch**

```bash
cd /Users/joe/Documents/code/agent-ledger
git checkout -b feat/activity-map
```

- [ ] **Step 2: Create the `ledger/` package**

```bash
mkdir ledger
touch ledger/__init__.py
```

- [ ] **Step 3: Move core modules into the package**

```bash
mv db.py ledger/db.py
mv parser.py ledger/parser.py
mv renderer.py ledger/renderer.py
```

- [ ] **Step 4: Update `ledger/db.py` — fix its self-reference import**

The file has no internal imports, so no changes needed to the module body. However, `renderer.py` imports from `db`, so update `ledger/renderer.py` line 1:

Change:
```python
from db import EXPORTS_DIR
```
To:
```python
from ledger.db import EXPORTS_DIR
```

- [ ] **Step 5: Update `daemon.py` — remove `sys.path.insert`, update imports**

Replace the top of `daemon.py`:
```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from db import (
    DB_PATH, PROJECTS_DIR, initialize, get_connection,
    upsert_session, insert_message, get_cursor, set_cursor
)
from parser import parse_line, session_info_from_event
```

With:
```python
from ledger.db import (
    DB_PATH, PROJECTS_DIR, initialize, get_connection,
    upsert_session, insert_message, get_cursor, set_cursor
)
from ledger.parser import parse_line, session_info_from_event
```

- [ ] **Step 6: Update `mcp_server.py` — remove `sys.path.insert`, update imports**

Replace the top of `mcp_server.py`:
```python
import sys
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
```

With:
```python
from ledger.db import DB_PATH, initialize, get_connection
from ledger.renderer import (
    render_time_range, render_search_results,
    write_markdown as _write_markdown,
    read_markdown as _read_markdown,
    default_export_path,
    EXPORTS_DIR,
)
```

- [ ] **Step 7: Smoke test — verify both entry points import cleanly**

```bash
python3 -c "import daemon" && echo "daemon OK"
python3 -c "import mcp_server" && echo "mcp_server OK"
```

Expected output:
```
daemon OK
mcp_server OK
```

- [ ] **Step 8: Commit**

```bash
git add ledger/ daemon.py mcp_server.py
git rm db.py parser.py renderer.py
git commit -m "refactor: move core modules into ledger/ package"
```

---

## Task 2: Test Scaffold + `bucket_size_minutes`

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `tests/test_activity.py`
- Create: `ledger/activity.py`

- [ ] **Step 1: Create test scaffold**

```bash
mkdir tests
touch tests/__init__.py
```

`tests/conftest.py`:
```python
import sqlite3
import pytest

@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript("""
        CREATE TABLE sessions (
            session_id TEXT PRIMARY KEY,
            project TEXT, cwd TEXT, git_branch TEXT,
            entrypoint TEXT, version TEXT,
            started_at TEXT, ended_at TEXT, last_seen_at TEXT
        );
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            subtype TEXT,
            content TEXT,
            tool_name TEXT,
            tool_use_id TEXT,
            is_error INTEGER,
            timestamp TEXT NOT NULL,
            date TEXT NOT NULL,
            hour INTEGER NOT NULL,
            sequence INTEGER,
            uuid TEXT,
            parent_uuid TEXT,
            is_sidechain INTEGER DEFAULT 0,
            agent_id TEXT
        );
        INSERT INTO sessions(session_id, project) VALUES ('sess-1', 'test-project');
    """)
    yield c
    c.close()
```

- [ ] **Step 2: Write failing tests for `bucket_size_minutes`**

`tests/test_activity.py`:
```python
from ledger.activity import bucket_size_minutes

def test_bucket_size_over_7_days():
    assert bucket_size_minutes(8 * 24 * 60 * 60) == 1440

def test_bucket_size_7_days_exact():
    assert bucket_size_minutes(7 * 24 * 60 * 60) == 1440

def test_bucket_size_3_days():
    assert bucket_size_minutes(3 * 24 * 60 * 60) == 60

def test_bucket_size_1_day_exact():
    assert bucket_size_minutes(24 * 60 * 60) == 60

def test_bucket_size_12_hours():
    assert bucket_size_minutes(12 * 60 * 60) == 15

def test_bucket_size_1_hour_exact():
    assert bucket_size_minutes(60 * 60) == 15

def test_bucket_size_30_minutes():
    assert bucket_size_minutes(30 * 60) == 5

def test_bucket_size_under_1_hour():
    assert bucket_size_minutes(59 * 60) == 5
```

- [ ] **Step 3: Run to verify they all fail**

```bash
pytest tests/test_activity.py -v
```

Expected: all fail with `ModuleNotFoundError: No module named 'ledger.activity'`

- [ ] **Step 4: Create `ledger/activity.py` with `bucket_size_minutes`**

```python
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
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_activity.py -v
```

Expected: all 8 pass.

- [ ] **Step 6: Commit**

```bash
git add tests/ ledger/activity.py
git commit -m "feat: add bucket_size_minutes + test scaffold"
```

---

## Task 3: `build_buckets`

**Files:**
- Modify: `tests/test_activity.py`
- Modify: `ledger/activity.py`

- [ ] **Step 1: Write failing tests for `build_buckets`**

Add to `tests/test_activity.py`:
```python
from ledger.activity import build_buckets

def _insert_user_msg(conn, ts, session_id="sess-1", is_sidechain=0):
    conn.execute("""
        INSERT INTO messages(session_id, role, subtype, timestamp, date, hour, is_sidechain)
        VALUES (?, 'user', 'human', ?, '2026-04-21', 14, ?)
    """, [session_id, ts, is_sidechain])
    conn.commit()

def test_build_buckets_empty_range(conn):
    result = build_buckets(conn, "2026-04-21T14:00:00Z", "2026-04-21T15:00:00Z", None, 15)
    assert len(result) == 4  # four 15-min buckets
    assert all(b["count"] == 0 for b in result)

def test_build_buckets_counts_user_messages(conn):
    _insert_user_msg(conn, "2026-04-21T14:05:00Z")
    _insert_user_msg(conn, "2026-04-21T14:07:00Z")
    _insert_user_msg(conn, "2026-04-21T14:32:00Z")
    result = build_buckets(conn, "2026-04-21T14:00:00Z", "2026-04-21T15:00:00Z", None, 15)
    assert result[0]["count"] == 2   # 14:00–14:15
    assert result[1]["count"] == 0   # 14:15–14:30
    assert result[2]["count"] == 1   # 14:30–14:45
    assert result[3]["count"] == 0   # 14:45–15:00

def test_build_buckets_excludes_sidechains(conn):
    _insert_user_msg(conn, "2026-04-21T14:05:00Z", is_sidechain=1)
    result = build_buckets(conn, "2026-04-21T14:00:00Z", "2026-04-21T15:00:00Z", None, 15)
    assert all(b["count"] == 0 for b in result)

def test_build_buckets_excludes_non_user_roles(conn):
    conn.execute("""
        INSERT INTO messages(session_id, role, subtype, timestamp, date, hour, is_sidechain)
        VALUES ('sess-1', 'assistant', 'text', '2026-04-21T14:05:00Z', '2026-04-21', 14, 0)
    """)
    conn.commit()
    result = build_buckets(conn, "2026-04-21T14:00:00Z", "2026-04-21T15:00:00Z", None, 15)
    assert all(b["count"] == 0 for b in result)

def test_build_buckets_filters_by_project(conn):
    conn.execute("INSERT INTO sessions(session_id, project) VALUES ('sess-other', 'other')")
    conn.commit()
    conn.execute("""
        INSERT INTO messages(session_id, role, subtype, timestamp, date, hour, is_sidechain)
        VALUES ('sess-other', 'user', 'human', '2026-04-21T14:05:00Z', '2026-04-21', 14, 0)
    """)
    conn.commit()
    result = build_buckets(conn, "2026-04-21T14:00:00Z", "2026-04-21T15:00:00Z", "test-project", 15)
    assert all(b["count"] == 0 for b in result)

def test_build_buckets_start_end_format(conn):
    result = build_buckets(conn, "2026-04-21T14:00:00Z", "2026-04-21T15:00:00Z", None, 15)
    assert result[0]["start"] == "2026-04-21T14:00:00Z"
    assert result[0]["end"]   == "2026-04-21T14:15:00Z"
    assert result[3]["start"] == "2026-04-21T14:45:00Z"
    assert result[3]["end"]   == "2026-04-21T15:00:00Z"
```

- [ ] **Step 2: Run to verify they fail**

```bash
pytest tests/test_activity.py -k "build_buckets" -v
```

Expected: fail with `ImportError`.

- [ ] **Step 3: Implement `build_buckets` in `ledger/activity.py`**

Add after `bucket_size_minutes`:
```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_activity.py -k "build_buckets" -v
```

Expected: all 5 pass.

- [ ] **Step 5: Commit**

```bash
git add tests/test_activity.py ledger/activity.py
git commit -m "feat: implement build_buckets with user-only, sidechain-excluded counting"
```

---

## Task 4: Natural Breaks Algorithm

**Files:**
- Modify: `tests/test_activity.py`
- Modify: `ledger/activity.py`

- [ ] **Step 1: Write failing tests for `_find_natural_breaks`**

Add to `tests/test_activity.py`:
```python
from ledger.activity import _find_natural_breaks

def test_natural_breaks_empty():
    assert _find_natural_breaks([]) == []

def test_natural_breaks_single_value():
    assert _find_natural_breaks([5]) == []

def test_natural_breaks_all_same():
    # No gap larger than median — no breaks
    assert _find_natural_breaks([3, 3, 3, 3]) == []

def test_natural_breaks_one_clear_gap():
    # Counts: [1, 1, 10, 11] — big gap between 1 and 10
    # gaps: [0, 9, 1] — median = 1, significant: [9] at index 1
    # break at sorted_counts[1] = 1
    breaks = _find_natural_breaks([1, 1, 10, 11])
    assert len(breaks) == 1
    assert breaks[0] == 1

def test_natural_breaks_two_clear_gaps():
    # Counts: [1, 2, 10, 11, 50, 51]
    # gaps: [1, 8, 1, 39, 1] — median = 1, significant: [8, 39]
    # breaks at sorted_counts[1]=2 and sorted_counts[3]=11
    breaks = _find_natural_breaks([1, 2, 10, 11, 50, 51])
    assert len(breaks) == 2
    assert breaks == [2, 11]

def test_natural_breaks_caps_at_two():
    # Even with three clear gaps, returns at most 2 breaks (the two largest)
    breaks = _find_natural_breaks([1, 10, 20, 30, 100])
    assert len(breaks) <= 2
```

- [ ] **Step 2: Run to verify they fail**

```bash
pytest tests/test_activity.py -k "natural_breaks" -v
```

Expected: fail with `ImportError`.

- [ ] **Step 3: Implement `_find_natural_breaks` in `ledger/activity.py`**

Add after `build_buckets`:
```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_activity.py -k "natural_breaks" -v
```

Expected: all 6 pass.

- [ ] **Step 5: Commit**

```bash
git add tests/test_activity.py ledger/activity.py
git commit -m "feat: implement natural break detection for activity classification"
```

---

## Task 5: Bucket Classification + Class Boundaries

**Files:**
- Modify: `tests/test_activity.py`
- Modify: `ledger/activity.py`

- [ ] **Step 1: Write failing tests for `_classify` and `_build_classes`**

Add to `tests/test_activity.py`:
```python
from ledger.activity import _classify, _build_classes

def test_classify_zero_always_quiet():
    assert _classify(0, []) == "quiet"
    assert _classify(0, [3]) == "quiet"
    assert _classify(0, [3, 10]) == "quiet"

def test_classify_no_breaks_active():
    assert _classify(5, []) == "active"
    assert _classify(1, []) == "active"

def test_classify_one_break():
    # break at 3: ≤3 → quiet, >3 → active
    assert _classify(3, [3]) == "quiet"
    assert _classify(4, [3]) == "active"

def test_classify_two_breaks():
    # breaks at [3, 10]: ≤3 → quiet, ≤10 → active, >10 → dense
    assert _classify(3, [3, 10]) == "quiet"
    assert _classify(7, [3, 10]) == "active"
    assert _classify(10, [3, 10]) == "active"
    assert _classify(11, [3, 10]) == "dense"

def test_build_classes_no_breaks():
    result = _build_classes([], min_nonzero=1, max_nonzero=8)
    assert set(result.keys()) == {"active"}

def test_build_classes_one_break():
    result = _build_classes([3], min_nonzero=1, max_nonzero=8)
    assert set(result.keys()) == {"quiet", "active"}
    assert result["quiet"]["max_count"] == 3
    assert result["active"]["min_count"] == 4

def test_build_classes_two_breaks():
    result = _build_classes([3, 10], min_nonzero=1, max_nonzero=15)
    assert set(result.keys()) == {"quiet", "active", "dense"}
    assert result["quiet"]["max_count"] == 3
    assert result["active"]["min_count"] == 4
    assert result["active"]["max_count"] == 10
    assert result["dense"]["min_count"] == 11
```

- [ ] **Step 2: Run to verify they fail**

```bash
pytest tests/test_activity.py -k "classify or build_classes" -v
```

Expected: fail with `ImportError`.

- [ ] **Step 3: Implement `_classify` and `_build_classes` in `ledger/activity.py`**

Add after `_find_natural_breaks`:
```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_activity.py -k "classify or build_classes" -v
```

Expected: all 9 pass.

- [ ] **Step 5: Commit**

```bash
git add tests/test_activity.py ledger/activity.py
git commit -m "feat: implement bucket classification and class boundary builder"
```

---

## Task 6: Suggested-Call Generation

**Files:**
- Modify: `tests/test_activity.py`
- Modify: `ledger/activity.py`

- [ ] **Step 1: Write failing tests for `_suggested_calls`**

Add to `tests/test_activity.py`:
```python
from ledger.activity import _suggested_calls

_WINDOW = {"start": "2026-04-21T14:00:00Z", "end": "2026-04-21T15:00:00Z", "count": 5}

def test_suggested_calls_quiet_returns_empty():
    result = _suggested_calls({**_WINDOW, "class": "quiet"}, bucket_minutes=60)
    assert result == []

def test_suggested_calls_active_suggests_write_markdown():
    result = _suggested_calls({**_WINDOW, "class": "active"}, bucket_minutes=60)
    assert len(result) == 1
    assert result[0]["tool"] == "write_markdown"
    assert result[0]["args"]["start"] == _WINDOW["start"]
    assert result[0]["args"]["end"] == _WINDOW["end"]

def test_suggested_calls_dense_non_leaf_suggests_activity_map():
    result = _suggested_calls({**_WINDOW, "class": "dense"}, bucket_minutes=60)
    assert len(result) == 1
    assert result[0]["tool"] == "get_activity_map"
    assert result[0]["args"]["start"] == _WINDOW["start"]
    assert result[0]["args"]["end"] == _WINDOW["end"]

def test_suggested_calls_dense_at_leaf_suggests_write_markdown():
    result = _suggested_calls({**_WINDOW, "class": "dense"}, bucket_minutes=5)
    assert len(result) == 1
    assert result[0]["tool"] == "write_markdown"

def test_suggested_calls_includes_reason():
    result = _suggested_calls({**_WINDOW, "class": "active"}, bucket_minutes=60)
    assert "reason" in result[0]
    assert isinstance(result[0]["reason"], str)
    assert len(result[0]["reason"]) > 0
```

- [ ] **Step 2: Run to verify they fail**

```bash
pytest tests/test_activity.py -k "suggested_calls" -v
```

Expected: fail with `ImportError`.

- [ ] **Step 3: Implement `_suggested_calls` in `ledger/activity.py`**

Add after `_build_classes`:
```python
_LEAF_BUCKET_MINUTES = 5


def _suggested_calls(bucket: dict, bucket_minutes: int) -> list:
    """Return structured suggested next-tool calls for a classified bucket."""
    cls = bucket["class"]
    if cls == "quiet":
        return []

    at_leaf = bucket_minutes <= _LEAF_BUCKET_MINUTES

    if cls == "dense" and not at_leaf:
        return [{
            "tool": "get_activity_map",
            "reason": "Window is dense — subdivide before reading to avoid missing nuance",
            "args": {"start": bucket["start"], "end": bucket["end"]},
        }]

    reason = (
        "Active window — ready to read at this granularity"
        if cls == "active"
        else "Dense window at minimum granularity — read directly"
    )
    return [{
        "tool": "write_markdown",
        "reason": reason,
        "args": {"start": bucket["start"], "end": bucket["end"]},
    }]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_activity.py -k "suggested_calls" -v
```

Expected: all 5 pass.

- [ ] **Step 5: Commit**

```bash
git add tests/test_activity.py ledger/activity.py
git commit -m "feat: implement suggested-call generation for activity map pipeline"
```

---

## Task 7: `activity_map` Integration Function

**Files:**
- Modify: `tests/test_activity.py`
- Modify: `ledger/activity.py`

- [ ] **Step 1: Write failing integration tests for `activity_map`**

Add to `tests/test_activity.py`:
```python
from ledger.activity import activity_map

def _insert_msgs(conn, timestamps):
    for ts in timestamps:
        conn.execute("""
            INSERT INTO messages(session_id, role, subtype, timestamp, date, hour, is_sidechain)
            VALUES ('sess-1', 'user', 'human', ?, '2026-04-21', 14, 0)
        """, [ts])
    conn.commit()

def test_activity_map_empty_range(conn):
    result = activity_map(conn, {
        "start": "2026-04-21T14:00:00Z",
        "end":   "2026-04-21T15:00:00Z",
    })
    assert result["total_user_messages"] == 0
    assert result["hot_windows"] == []
    assert "No user activity" in result["interpretation"]

def test_activity_map_returns_required_keys(conn):
    _insert_msgs(conn, ["2026-04-21T14:05:00Z", "2026-04-21T14:10:00Z"])
    result = activity_map(conn, {
        "start": "2026-04-21T14:00:00Z",
        "end":   "2026-04-21T15:00:00Z",
    })
    for key in ("bucket_size_minutes", "total_user_messages", "interpretation",
                "classes", "histogram", "hot_windows"):
        assert key in result, f"Missing key: {key}"

def test_activity_map_histogram_covers_full_range(conn):
    result = activity_map(conn, {
        "start": "2026-04-21T14:00:00Z",
        "end":   "2026-04-21T15:00:00Z",
    })
    # 1 hour at 5-min buckets = 12 buckets
    assert len(result["histogram"]) == 12

def test_activity_map_hot_windows_excludes_quiet(conn):
    _insert_msgs(conn, ["2026-04-21T14:05:00Z"])
    result = activity_map(conn, {
        "start": "2026-04-21T14:00:00Z",
        "end":   "2026-04-21T15:00:00Z",
    })
    for w in result["hot_windows"]:
        assert w["class"] != "quiet"

def test_activity_map_hot_windows_sorted_by_count_desc(conn):
    _insert_msgs(conn, [
        "2026-04-21T14:05:00Z",
        "2026-04-21T14:32:00Z",
        "2026-04-21T14:33:00Z",
        "2026-04-21T14:34:00Z",
    ])
    result = activity_map(conn, {
        "start": "2026-04-21T14:00:00Z",
        "end":   "2026-04-21T15:00:00Z",
    })
    counts = [w["count"] for w in result["hot_windows"]]
    assert counts == sorted(counts, reverse=True)

def test_activity_map_total_count(conn):
    _insert_msgs(conn, ["2026-04-21T14:05:00Z", "2026-04-21T14:10:00Z", "2026-04-21T14:35:00Z"])
    result = activity_map(conn, {
        "start": "2026-04-21T14:00:00Z",
        "end":   "2026-04-21T15:00:00Z",
    })
    assert result["total_user_messages"] == 3

def test_activity_map_project_filter(conn):
    conn.execute("INSERT INTO sessions(session_id, project) VALUES ('sess-2', 'other')")
    conn.execute("""
        INSERT INTO messages(session_id, role, subtype, timestamp, date, hour, is_sidechain)
        VALUES ('sess-2', 'user', 'human', '2026-04-21T14:05:00Z', '2026-04-21', 14, 0)
    """)
    conn.commit()
    result = activity_map(conn, {
        "start":   "2026-04-21T14:00:00Z",
        "end":     "2026-04-21T15:00:00Z",
        "project": "test-project",
    })
    assert result["total_user_messages"] == 0
```

- [ ] **Step 2: Run to verify they fail**

```bash
pytest tests/test_activity.py -k "activity_map" -v
```

Expected: fail with `ImportError`.

- [ ] **Step 3: Implement `activity_map` in `ledger/activity.py`**

Add at the end of `ledger/activity.py`:
```python
def activity_map(conn, params: dict) -> dict:
    """Main entry point for the get_activity_map MCP tool."""
    start   = params.get("start", "").strip()
    end     = params.get("end", "").strip()
    project = params.get("project", "").strip() or None

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
        f"Jenks found {k} natural tier(s) (k={k}). "
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
```

- [ ] **Step 4: Run all tests to verify they pass**

```bash
pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add tests/test_activity.py ledger/activity.py
git commit -m "feat: implement activity_map integration function"
```

---

## Task 8: Wire into `mcp_server.py` + Update Tool Descriptions

**Files:**
- Modify: `mcp_server.py`

- [ ] **Step 1: Add the import for `activity_map`**

In `mcp_server.py`, add to the imports block:
```python
from ledger.activity import activity_map as _activity_map
```

- [ ] **Step 2: Add the `get_activity_map` handler function**

Add this function alongside the other handler functions (after `list_projects`):
```python
def get_activity_map(conn, p: dict) -> dict:
    start = p.get("start", "").strip()
    end   = p.get("end",   "").strip()
    if not start or not end:
        return {"error": "start and end are required (ISO8601)"}
    return _activity_map(conn, p)
```

- [ ] **Step 3: Register the tool in the `TOOLS` list**

Add this entry to the `TOOLS` list in `mcp_server.py`:
```python
{
    "name": "get_activity_map",
    "description": (
        "Identify where user activity is concentrated in a time range. "
        "Returns a histogram of all time buckets and a ranked list of significant windows, "
        "each classified as 'active' or 'dense' with structured suggested_calls pointing to "
        "the next tool in the pipeline. "
        "Use this before render_markdown or write_markdown for any range longer than ~30 minutes "
        "— it tells you where to look and how carefully to read each window. "
        "Dense windows suggest a recursive get_activity_map call to subdivide further. "
        "Active windows suggest write_markdown. "
        "Quiet windows can be skipped."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "start":   {"type": "string", "description": "ISO8601 start time"},
            "end":     {"type": "string", "description": "ISO8601 end time"},
            "project": {"type": "string", "description": "Filter by project name (optional)"},
        },
        "required": ["start", "end"]
    }
},
```

- [ ] **Step 4: Add the dispatch entry**

In the `dispatch` dict inside `handle()`, add:
```python
"get_activity_map": lambda: get_activity_map(conn, args),
```

- [ ] **Step 5: Update the description of `query_time_range`**

Find the existing `query_time_range` tool entry in `TOOLS` and replace its `"description"` value with:
```python
"description": (
    "Retrieve raw messages as structured JSON. "
    "Has a hard 200-row limit — use get_activity_map + render_markdown/write_markdown "
    "instead for any human-readable summary. "
    "This tool is for programmatic inspection of specific messages, not for summarization."
),
```

- [ ] **Step 6: Update the description of `render_markdown`**

Replace its `"description"` value with:
```python
"description": (
    "Render session history as formatted markdown for a time window. "
    "Best used on windows already identified as 'active' by get_activity_map. "
    "For 'dense' windows or ranges longer than ~30 minutes, use write_markdown instead "
    "to avoid context overflow."
),
```

- [ ] **Step 7: Update the description of `write_markdown`**

Replace its `"description"` value with:
```python
"description": (
    "Render session history as markdown and write to disk, then read back with read_markdown. "
    "Preferred over render_markdown for any window flagged 'dense' by get_activity_map, "
    "or for ranges longer than ~30 minutes. "
    "If path is omitted, writes to the default exports directory. "
    "Use for exporting sessions for sharing or pushing to Notion."
),
```

- [ ] **Step 8: Smoke test the MCP server**

```bash
echo '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | python3 mcp_server.py
```

Expected: JSON response containing `get_activity_map` in the tools list, and no import errors.

- [ ] **Step 9: Run full test suite**

```bash
pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 10: Commit**

```bash
git add mcp_server.py
git commit -m "feat: add get_activity_map tool to MCP server, update tool descriptions"
```

---

## Task 9: Open Pull Request

- [ ] **Step 1: Verify the branch is clean**

```bash
git status
git log main..HEAD --oneline
```

Expected log:
```
feat: add get_activity_map tool to MCP server, update tool descriptions
feat: implement activity_map integration function
feat: implement suggested-call generation for activity map pipeline
feat: implement bucket classification and class boundary builder
feat: implement natural break detection for activity classification
feat: implement build_buckets with user-only, sidechain-excluded counting
feat: add bucket_size_minutes + test scaffold
refactor: move core modules into ledger/ package
docs: add activity map design spec
```

- [ ] **Step 2: Push the branch**

```bash
git push -u origin feat/activity-map
```

- [ ] **Step 3: Open the PR**

```bash
gh pr create \
  --title "feat: activity map — scale-aware hot-window detection for agent ledger" \
  --body "$(cat <<'EOF'
## Summary

- Restructures flat module layout into a `ledger/` package (removes `sys.path.insert` hacks)
- Adds `ledger/activity.py`: scale-aware bucketing, Jenks natural-break classification, suggested-call generation
- Adds `get_activity_map` MCP tool that returns a histogram + ranked hot windows with structured `suggested_calls`
- Updates descriptions of `query_time_range`, `render_markdown`, `write_markdown` to reference the pipeline

## How it works

Claude calls `get_activity_map(start, end)` before reading content. The tool:
1. Auto-selects bucket granularity based on range length (5 min → hourly → daily)
2. Counts only user messages (sidechain-excluded)
3. Runs natural-break detection to classify buckets as `quiet` / `active` / `dense`
4. Annotates each hot window with `suggested_calls` pointing to the next step

Dense windows suggest a recursive `get_activity_map` drill-down. Active windows suggest `write_markdown`. Quiet windows are skipped.

## Test plan

- [ ] `pytest tests/ -v` passes
- [ ] `echo '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | python3 mcp_server.py` lists `get_activity_map`
- [ ] Ask Claude "what did I do today?" and verify it uses `get_activity_map` first

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---
