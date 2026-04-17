"""
Database module for agent-ledger.
Pure Python stdlib — sqlite3 only.
"""

import logging
import platform
import sqlite3
from pathlib import Path

log = logging.getLogger(__name__)

# ── paths ─────────────────────────────────────────────────────────────────────

DATA_DIR        = Path.home() / "Documents" / "agent-ledger"
DB_PATH         = DATA_DIR / "memory.db"
EXPORTS_DIR     = DATA_DIR / "exports" / "markdown"
PROJECTS_DIR    = Path.home() / ".claude" / "projects"


def ensure_directories():
    """Create all required directories if they don't exist."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)


def _zstd_extension_path() -> Path | None:
    system = platform.system().lower()
    machine = platform.machine().lower()
    arch = "arm64" if machine in ("arm64", "aarch64") else "x86_64"
    ext = "dylib" if system == "darwin" else "so"
    p = Path(__file__).parent / "extensions" / f"zstd_vfs-{system}-{arch}.{ext}"
    return p if p.exists() else None


def get_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    ensure_directories()
    ext = _zstd_extension_path()
    if ext:
        loader = sqlite3.connect(":memory:")
        loader.enable_load_extension(True)
        loader.load_extension(str(ext))
        loader.close()
        conn = sqlite3.connect(f"file:{db_path}?vfs=zstd", uri=True)
    else:
        if list(Path(__file__).parent.glob("extensions/zstd_vfs-*")):
            log.warning("zstd_vfs extension not found for this platform — using uncompressed storage")
        conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def initialize(db_path: Path = DB_PATH):
    """Create all tables and indexes if they don't exist."""
    ensure_directories()
    conn = get_connection(db_path)
    with conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id      TEXT PRIMARY KEY,
                project         TEXT,
                cwd             TEXT,
                git_branch      TEXT,
                entrypoint      TEXT,
                version         TEXT,
                started_at      TEXT,
                ended_at        TEXT,
                last_seen_at    TEXT
            );

            CREATE TABLE IF NOT EXISTS messages (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id      TEXT NOT NULL REFERENCES sessions(session_id),
                role            TEXT NOT NULL,
                subtype         TEXT,
                content         TEXT,
                tool_name       TEXT,
                tool_use_id     TEXT,
                is_error        INTEGER,
                timestamp       TEXT NOT NULL,
                date            TEXT NOT NULL,
                hour            INTEGER NOT NULL,
                sequence        INTEGER,
                uuid            TEXT UNIQUE,
                parent_uuid     TEXT,
                is_sidechain    INTEGER DEFAULT 0,
                agent_id        TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_messages_session
                ON messages(session_id);
            CREATE INDEX IF NOT EXISTS idx_messages_date
                ON messages(date);
            CREATE INDEX IF NOT EXISTS idx_messages_hour
                ON messages(date, hour);
            CREATE INDEX IF NOT EXISTS idx_messages_timestamp
                ON messages(timestamp);
            CREATE INDEX IF NOT EXISTS idx_messages_role
                ON messages(role);
            CREATE INDEX IF NOT EXISTS idx_sessions_project
                ON sessions(project);
            CREATE INDEX IF NOT EXISTS idx_sessions_started
                ON sessions(started_at);

            CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
                content,
                project,
                git_branch,
                role,
                tool_name,
                content='messages',
                content_rowid='id',
                tokenize='porter unicode61'
            );

            CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
                INSERT INTO messages_fts(rowid, content, project, git_branch, role, tool_name)
                SELECT NEW.id, NEW.content,
                       (SELECT project FROM sessions WHERE session_id = NEW.session_id),
                       (SELECT git_branch FROM sessions WHERE session_id = NEW.session_id),
                       NEW.role, NEW.tool_name;
            END;

            CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
                INSERT INTO messages_fts(messages_fts, rowid, content, project, git_branch, role, tool_name)
                VALUES('delete', OLD.id, OLD.content,
                       (SELECT project FROM sessions WHERE session_id = OLD.session_id),
                       (SELECT git_branch FROM sessions WHERE session_id = OLD.session_id),
                       OLD.role, OLD.tool_name);
            END;

            CREATE TRIGGER IF NOT EXISTS messages_au AFTER UPDATE ON messages BEGIN
                INSERT INTO messages_fts(messages_fts, rowid, content, project, git_branch, role, tool_name)
                VALUES('delete', OLD.id, OLD.content,
                       (SELECT project FROM sessions WHERE session_id = OLD.session_id),
                       (SELECT git_branch FROM sessions WHERE session_id = OLD.session_id),
                       OLD.role, OLD.tool_name);
                INSERT INTO messages_fts(rowid, content, project, git_branch, role, tool_name)
                SELECT NEW.id, NEW.content,
                       (SELECT project FROM sessions WHERE session_id = NEW.session_id),
                       (SELECT git_branch FROM sessions WHERE session_id = NEW.session_id),
                       NEW.role, NEW.tool_name;
            END;

            CREATE TABLE IF NOT EXISTS file_cursors (
                file_path       TEXT PRIMARY KEY,
                last_line       INTEGER NOT NULL DEFAULT 0,
                last_mtime      REAL,
                session_id      TEXT
            );
        """)
    conn.close()


def upsert_session(conn: sqlite3.Connection, session_id: str, **kwargs):
    fields = list(kwargs.keys())
    values = list(kwargs.values())
    placeholders = ", ".join("?" * len(values))
    cols = ", ".join(fields)
    updates = ", ".join(f"{f}=excluded.{f}" for f in fields if f != "started_at")
    conn.execute(f"""
        INSERT INTO sessions(session_id, {cols})
        VALUES(?, {placeholders})
        ON CONFLICT(session_id) DO UPDATE SET {updates}
    """, [session_id] + values)


def insert_message(conn: sqlite3.Connection, **kwargs) -> int:
    fields = list(kwargs.keys())
    values = list(kwargs.values())
    placeholders = ", ".join("?" * len(values))
    cols = ", ".join(fields)
    cur = conn.execute(f"""
        INSERT OR IGNORE INTO messages({cols}) VALUES({placeholders})
    """, values)
    return cur.lastrowid


def get_cursor(conn: sqlite3.Connection, file_path: str) -> tuple:
    row = conn.execute(
        "SELECT last_line, last_mtime FROM file_cursors WHERE file_path=?",
        [file_path]
    ).fetchone()
    if row:
        return row["last_line"], row["last_mtime"]
    return 0, None


def set_cursor(conn: sqlite3.Connection, file_path: str, last_line: int,
               last_mtime: float, session_id: str):
    conn.execute("""
        INSERT INTO file_cursors(file_path, last_line, last_mtime, session_id)
        VALUES(?, ?, ?, ?)
        ON CONFLICT(file_path) DO UPDATE SET
            last_line=excluded.last_line,
            last_mtime=excluded.last_mtime,
            session_id=excluded.session_id
    """, [file_path, last_line, last_mtime, session_id])
