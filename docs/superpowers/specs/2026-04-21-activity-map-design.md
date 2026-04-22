# Activity Map Design

**Date:** 2026-04-21
**Status:** Approved

## Problem

When Claude is asked to summarize a time range ("tell me everything that happened today"), it has no good entry point. `query_time_range` returns raw JSON with a 200-row limit -- easy to hit, easy to mis-use as a summarization tool. `render_markdown` and `write_markdown` are the right tools but produce output that can overflow context for large ranges, and nothing guides Claude toward them. The result is Claude doing its own parsing on truncated data.

The fix is a two-phase pipeline:
1. A lightweight activity map that tells Claude *where* activity is concentrated and *how carefully* to read each window
2. Existing rendering tools (`write_markdown`, `render_markdown`) consume the map's output

## Package Restructure

The flat file layout is replaced with a proper package. The `sys.path.insert` hacks in both entry points go away.

```
agent-ledger/
  ledger/                  # core library package
    __init__.py
    db.py
    parser.py
    renderer.py
    activity.py            # NEW
  daemon.py                # entry point
  mcp_server.py            # entry point
  install.sh
  README.md
  CLAUDE.md
```

Entry points import from `ledger.*`. No external dependencies added. Pure stdlib throughout.

## New Tool: `get_activity_map`

### Purpose

Identify where user activity is concentrated in a time range. Returns a histogram of all buckets and a ranked list of significant windows, each classified and annotated with structured `suggested_calls` pointing to the next tool in the pipeline.

Claude should call this before `render_markdown` or `write_markdown` for any range longer than ~30 minutes.

### Input Schema

| Field | Type | Required | Description |
|---|---|---|---|
| `start` | ISO8601 string | yes | Range start |
| `end` | ISO8601 string | yes | Range end |
| `project` | string | no | Filter by project name |

### Return Shape

```json
{
  "bucket_size_minutes": 60,
  "total_user_messages": 47,
  "interpretation": "47 user messages across 6 hours. Jenks found 3 natural tiers (k=3). Two dense windows (15:00–16:00, 18:00–19:00) contain 38 of those messages and warrant subdivision before reading. Three active windows are readable directly. Fourteen buckets were quiet and can be skipped.",
  "classes": {
    "quiet":  {"max_count": 1},
    "active": {"min_count": 2, "max_count": 8},
    "dense":  {"min_count": 9}
  },
  "histogram": [
    {"start": "...", "end": "...", "count": 0,  "class": "quiet"},
    {"start": "...", "end": "...", "count": 18, "class": "dense"},
    ...
  ],
  "hot_windows": [
    {
      "start": "2026-04-21T15:00Z",
      "end":   "2026-04-21T16:00Z",
      "count": 18,
      "class": "dense",
      "suggested_calls": [
        {
          "tool": "get_activity_map",
          "reason": "Window is dense — subdivide before reading to avoid missing nuance",
          "args": {"start": "2026-04-21T15:00Z", "end": "2026-04-21T16:00Z"}
        }
      ]
    },
    {
      "start": "2026-04-21T18:00Z",
      "end":   "2026-04-21T19:00Z",
      "count": 9,
      "class": "active",
      "suggested_calls": [
        {
          "tool": "write_markdown",
          "reason": "Active window — ready to read at this granularity",
          "args": {"start": "2026-04-21T18:00Z", "end": "2026-04-21T19:00Z"}
        }
      ]
    }
  ]
}
```

`hot_windows` contains only `active` and `dense` buckets, sorted by count descending. `quiet` buckets appear in `histogram` only.

The `classes` field contains only the tiers that exist for the given k: k=1 produces `{"active": {...}}` only; k=2 produces `{"quiet": {...}, "active": {...}}`; k=3 produces all three. `dense` is never present unless k=3.

## Algorithm (`ledger/activity.py`)

### Scale-Aware Bucket Sizing

Bucket granularity is selected automatically from the range length:

| Range length | Bucket size |
|---|---|
| > 7 days | 1440 min (daily) |
| 1–7 days | 60 min (hourly) |
| 1–24 hours | 15 min |
| < 1 hour | 5 min |

### Data Source

Query: `messages` joined to `sessions`, filtered to:
- `role = 'user'`
- `subtype = 'human'`
- `is_sidechain = 0`
- `timestamp` within range
- optionally `project` matches

User messages are the only signal. Assistant turns and tool calls are excluded -- they measure how chatty the model was, not how much the user engaged.

### Jenks Natural Breaks

Operates on non-zero bucket counts only. Zero-count buckets are `quiet` by definition and excluded from Jenks input to avoid skewing gap detection.

**Auto-selecting k:**

A "natural gap" is defined as a gap in the sorted count distribution larger than the median gap size. k is the number of natural gaps found, capped at 2 (giving k=3 maximum: `quiet`, `active`, `dense`).

- 0 natural gaps → k=1: all non-zero buckets are `active`
- 1 natural gap → k=2: `quiet` + `active`
- 2+ natural gaps → k=3: `quiet` + `active` + `dense`

If there are zero non-zero buckets, return an empty `hot_windows` list and set `interpretation` to "No user activity found in this range."

If fewer than 2 non-zero buckets exist, skip Jenks and label the single non-zero bucket `active`.

**Class labels** (always in this order, from lowest to highest count):
- Class 0 → `quiet`
- Class 1 → `active`
- Class 2 → `dense` (only present when k=3)

### Suggested-Call Generation

For each `active` or `dense` window:

| Window class | Bucket at leaf scale (5 min)? | Suggested tool |
|---|---|---|
| `dense` | no | `get_activity_map` (same start/end -- drill down) |
| `dense` | yes | `write_markdown` (nowhere smaller to go) |
| `active` | either | `write_markdown` |

`write_markdown` is always preferred over `render_markdown` in suggested calls to avoid context overflow. Each suggested call includes a `reason` string Claude can surface to the user.

### Recursive Drill-Down Example

```
get_activity_map(month)           → hot days: Apr 7, Apr 14, Apr 21
  get_activity_map(Apr 21)        → hot hours: 14:00–16:00, 18:00–19:00
    write_markdown(14:00–16:00)   → reads content at correct fidelity
    write_markdown(18:00–19:00)   → reads content at correct fidelity
```

## Updated Tool Descriptions

Existing tools get description-only updates to reference their place in the pipeline.

**`query_time_range`**
> Retrieve raw messages as structured JSON. Has a hard 200-row limit. Use `get_activity_map` + `render_markdown`/`write_markdown` instead for any human-readable summary. This tool is for programmatic inspection of specific messages, not for summarization.

**`render_markdown`**
> Render session history as formatted markdown for a time window. Best used on windows already identified as `active` by `get_activity_map`. For `dense` windows or ranges longer than ~30 minutes, use `write_markdown` instead to avoid context overflow.

**`write_markdown`**
> Render session history as markdown and write to disk, then read back with `read_markdown`. Preferred over `render_markdown` for any window flagged `dense` by `get_activity_map`, or for ranges longer than ~30 minutes.

## Out of Scope

- Weighting by message type (user vs assistant vs tool) -- not needed; user-only signal is sufficient
- Exposing k as a parameter -- auto-selection from gap detection handles all cases
- Modifying the daemon or DB schema -- activity map is a pure read
