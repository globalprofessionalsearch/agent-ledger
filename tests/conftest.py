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
