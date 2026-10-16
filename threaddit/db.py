import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    username_key TEXT NOT NULL UNIQUE,
    account_type TEXT NOT NULL CHECK (account_type IN ('human', 'agent')),
    status TEXT NOT NULL CHECK (status IN ('pending', 'approved')),
    is_superadmin INTEGER NOT NULL DEFAULT 0,
    token_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS one_superadmin ON users (is_superadmin) WHERE is_superadmin = 1;

CREATE TABLE IF NOT EXISTS areas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    name_key TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL DEFAULT '',
    created_by INTEGER NOT NULL REFERENCES users (id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS threads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    area_id INTEGER NOT NULL REFERENCES areas (id),
    title TEXT NOT NULL,
    owner_id INTEGER NOT NULL REFERENCES users (id),
    created_at TEXT NOT NULL,
    last_activity_at TEXT NOT NULL,
    pinned INTEGER NOT NULL DEFAULT 0,
    closed_reason TEXT CHECK (closed_reason IN ('completed', 'archived')),
    closed_at TEXT,
    closed_by INTEGER REFERENCES users (id)
);
CREATE INDEX IF NOT EXISTS threads_area ON threads (area_id);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id INTEGER NOT NULL REFERENCES threads (id),
    parent_id INTEGER REFERENCES messages (id),
    author_id INTEGER NOT NULL REFERENCES users (id),
    body TEXT NOT NULL,
    created_at TEXT NOT NULL,
    is_op INTEGER NOT NULL DEFAULT 0,
    score INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS messages_thread ON messages (thread_id);
CREATE INDEX IF NOT EXISTS messages_parent ON messages (parent_id);

CREATE TABLE IF NOT EXISTS reactions (
    message_id INTEGER NOT NULL REFERENCES messages (id),
    user_id INTEGER NOT NULL REFERENCES users (id),
    emoji TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (message_id, user_id, emoji)
);

CREATE TABLE IF NOT EXISTS votes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER NOT NULL REFERENCES messages (id),
    user_id INTEGER NOT NULL REFERENCES users (id),
    delta INTEGER NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS attention (
    message_id INTEGER NOT NULL REFERENCES messages (id),
    user_id INTEGER NOT NULL REFERENCES users (id),
    reason TEXT NOT NULL CHECK (reason IN ('mention', 'reply', 'agent_message')),
    status TEXT NOT NULL CHECK (status IN ('unacknowledged', 'processing', 'processed', 'acknowledged')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (message_id, user_id)
);
CREATE INDEX IF NOT EXISTS attention_user ON attention (user_id, status);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    actor_id INTEGER NOT NULL REFERENCES users (id),
    area_id INTEGER REFERENCES areas (id),
    thread_id INTEGER REFERENCES threads (id),
    message_id INTEGER REFERENCES messages (id),
    detail TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
"""


class Database:
    """File-backed SQLite. One connection and one transaction per request."""

    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        conn = self._connect()
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(SCHEMA)
        finally:
            conn.close()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            self.path, timeout=10, isolation_level=None, check_same_thread=False
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @contextmanager
    def tx(self, write: bool):
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield conn
            conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()
