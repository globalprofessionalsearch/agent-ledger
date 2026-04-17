#!/usr/bin/env python3
"""
agent-ledger daemon
Watches ~/.claude/projects/**/*.jsonl and ingests new lines into memory.db.

Usage:
    python3 daemon.py [--interval SECONDS] [--session-timeout SECONDS] [--debug]

Pure Python stdlib. No external dependencies.
"""

import argparse
import json
import logging
import os
import signal
import sys
import time
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent))

from db import (
    DB_PATH, PROJECTS_DIR, initialize, get_connection,
    upsert_session, insert_message, get_cursor, set_cursor
)
from parser import parse_line, session_info_from_event

# ── logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("agent-ledger")

# ── defaults ──────────────────────────────────────────────────────────────────

DEFAULT_POLL_INTERVAL  = 30    # seconds
DEFAULT_SESSION_TIMEOUT = 300  # seconds of inactivity → session marked ended


# ── helpers ───────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _count_lines(file_path: Path, skip: int) -> int:
    """Count lines in file beyond skip."""
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            return sum(1 for i, _ in enumerate(f) if i >= skip)
    except OSError:
        return 0


def _maybe_mark_ended(conn, file_path_str: str, mtime: float, timeout: int):
    """If file hasn't been modified for `timeout` seconds, mark its session ended."""
    if time.time() - mtime < timeout:
        return

    row = conn.execute(
        "SELECT session_id FROM file_cursors WHERE file_path=?",
        [file_path_str]
    ).fetchone()
    if not row or not row["session_id"]:
        return

    sid = row["session_id"]
    existing = conn.execute(
        "SELECT ended_at FROM sessions WHERE session_id=?", [sid]
    ).fetchone()
    if existing and existing["ended_at"]:
        return  # already marked

    ended_at = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
    with conn:
        conn.execute(
            "UPDATE sessions SET ended_at=? WHERE session_id=?",
            [ended_at, sid]
        )
    log.info(f"Session ended: {sid[:8]}... at {ended_at}")


# ── ingestion ─────────────────────────────────────────────────────────────────

def ingest_file(conn, file_path: Path, session_timeout: int):
    """Read any new lines from file_path since the last cursor position."""
    path_str = str(file_path)

    try:
        stat = file_path.stat()
    except FileNotFoundError:
        return

    last_line, last_mtime = get_cursor(conn, path_str)

    # Skip if file unchanged
    if last_mtime is not None and stat.st_mtime <= last_mtime:
        _maybe_mark_ended(conn, path_str, stat.st_mtime, session_timeout)
        return

    new_rows = 0
    session_id = None
    current_line = 0

    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            for lineno, raw in enumerate(f, start=1):
                current_line = lineno
                if lineno <= last_line:
                    continue

                parsed_rows = parse_line(raw)
                if not parsed_rows:
                    continue

                # Extract session info from the raw event once
                try:
                    event = json.loads(raw.strip())
                    info = session_info_from_event(event)
                    ts = event.get("timestamp", _now_iso())
                except Exception:
                    info = {}
                    ts = _now_iso()

                for row in parsed_rows:
                    # Session metadata pseudo-row
                    if row.get("_meta") == "session":
                        sid = row["session_id"]
                        if sid:
                            session_id = sid
                            with conn:
                                upsert_session(conn, sid,
                                               started_at=ts,
                                               last_seen_at=ts)
                        continue

                    sid = row.get("session_id", "")
                    if not sid:
                        continue

                    session_id = sid

                    # Upsert session with latest metadata
                    with conn:
                        upsert_session(conn, sid,
                                       project=info.get("project"),
                                       cwd=info.get("cwd"),
                                       git_branch=info.get("git_branch"),
                                       entrypoint=info.get("entrypoint"),
                                       version=info.get("version"),
                                       started_at=ts,
                                       last_seen_at=ts)

                        msg_fields = {k: v for k, v in row.items()
                                      if k != "_meta" and v is not None}
                        insert_message(conn, **msg_fields)

                    new_rows += 1

    except OSError as e:
        log.warning(f"Could not read {file_path}: {e}")
        return

    if new_rows > 0:
        log.info(f"Ingested {new_rows} rows from {file_path.name}")

    with conn:
        set_cursor(conn, path_str, current_line, stat.st_mtime, session_id or "")

    _maybe_mark_ended(conn, path_str, stat.st_mtime, session_timeout)


# ── discovery ─────────────────────────────────────────────────────────────────

def find_jsonl_files() -> list:
    if not PROJECTS_DIR.exists():
        log.warning(f"Projects directory not found: {PROJECTS_DIR}")
        return []
    return sorted(PROJECTS_DIR.rglob("*.jsonl"))


# ── main loop ─────────────────────────────────────────────────────────────────

def run(poll_interval: int, session_timeout: int):
    log.info("agent-ledger daemon starting")
    log.info(f"  DB:              {DB_PATH}")
    log.info(f"  Projects dir:    {PROJECTS_DIR}")
    log.info(f"  Poll interval:   {poll_interval}s")
    log.info(f"  Session timeout: {session_timeout}s")

    initialize()
    conn = get_connection()

    running = True

    def _stop(sig, frame):
        nonlocal running
        log.info("Shutting down...")
        running = False

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    while running:
        files = find_jsonl_files()
        log.debug(f"Scanning {len(files)} JSONL file(s)")
        for f in files:
            if not running:
                break
            try:
                ingest_file(conn, f, session_timeout)
            except Exception as e:
                log.error(f"Error processing {f}: {e}", exc_info=True)

        # Sleep in small increments so SIGINT responds quickly
        for _ in range(poll_interval * 2):
            if not running:
                break
            time.sleep(0.5)

    conn.close()
    log.info("Daemon stopped.")


# ── entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="agent-ledger daemon")
    parser.add_argument("--interval", type=int, default=DEFAULT_POLL_INTERVAL,
                        help=f"Poll interval in seconds (default: {DEFAULT_POLL_INTERVAL})")
    parser.add_argument("--session-timeout", type=int, default=DEFAULT_SESSION_TIMEOUT,
                        help=f"Inactivity seconds before session marked ended "
                             f"(default: {DEFAULT_SESSION_TIMEOUT})")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    run(args.poll_interval if hasattr(args, 'poll_interval') else args.interval,
        args.session_timeout)


if __name__ == "__main__":
    main()
