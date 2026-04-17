#!/usr/bin/env python3
"""
Converts memory.db to zstd page-compressed format in-place.

Usage:
    python3 migrate_compress.py [--dry-run]

What it does:
    1. Loads the zstd_vfs extension
    2. VACUUMs the existing database into a temporary compressed copy
    3. Verifies message and session counts match
    4. Renames the original to memory.db.bak
    5. Moves the compressed copy into place as memory.db

The .bak file is kept until you manually remove it.
"""

import argparse
import shutil
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from db import DB_PATH, _zstd_extension_path


def _count(conn: sqlite3.Connection, table: str) -> int:
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def migrate(dry_run: bool = False):
    ext = _zstd_extension_path()
    if not ext:
        print("ERROR: zstd_vfs extension not found for this platform.")
        print("  Run the 'Build Extensions' GitHub Actions workflow first.")
        sys.exit(1)

    if not DB_PATH.exists():
        print(f"ERROR: Database not found: {DB_PATH}")
        sys.exit(1)

    tmp_path = DB_PATH.with_suffix(".db.zstd_tmp")
    bak_path = DB_PATH.with_suffix(".db.bak")

    print(f"Source:      {DB_PATH} ({DB_PATH.stat().st_size / 1024**2:.1f} MB)")
    print(f"Extension:   {ext}")
    print(f"Destination: {tmp_path}")
    print()

    if dry_run:
        print("[dry-run] No changes made.")
        return

    # Load extension and get source counts
    src = sqlite3.connect(str(DB_PATH))
    src.enable_load_extension(True)
    src.load_extension(str(ext))

    src_messages = _count(src, "messages")
    src_sessions  = _count(src, "sessions")
    print(f"Source rows: {src_messages:,} messages, {src_sessions:,} sessions")

    # VACUUM INTO compressed copy
    print("Compressing (this may take a minute)...")
    src.execute(f"VACUUM INTO 'file:{tmp_path}?vfs=zstd'")
    src.close()

    # Verify counts in compressed copy
    loader = sqlite3.connect(":memory:")
    loader.enable_load_extension(True)
    loader.load_extension(str(ext))
    loader.close()

    dst = sqlite3.connect(f"file:{tmp_path}?vfs=zstd", uri=True)
    dst_messages = _count(dst, "messages")
    dst_sessions  = _count(dst, "sessions")
    dst.close()

    print(f"Output rows: {dst_messages:,} messages, {dst_sessions:,} sessions")

    if dst_messages != src_messages or dst_sessions != src_sessions:
        tmp_path.unlink(missing_ok=True)
        print("ERROR: Row count mismatch — aborting. Original database is unchanged.")
        sys.exit(1)

    # Swap files
    DB_PATH.rename(bak_path)
    tmp_path.rename(DB_PATH)

    compressed_size = DB_PATH.stat().st_size / 1024**2
    original_size   = bak_path.stat().st_size / 1024**2
    reduction = (1 - compressed_size / original_size) * 100

    print()
    print(f"Done. {original_size:.1f} MB → {compressed_size:.1f} MB ({reduction:.0f}% reduction)")
    print(f"Backup:  {bak_path}")
    print("Remove the backup once you've confirmed everything works:")
    print(f"  rm {bak_path}")


def main():
    parser = argparse.ArgumentParser(description="Migrate memory.db to zstd page compression")
    parser.add_argument("--dry-run", action="store_true", help="Check extension availability without modifying any files")
    args = parser.parse_args()
    migrate(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
