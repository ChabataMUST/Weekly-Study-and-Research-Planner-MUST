"""Persistent storage for the local, single-user feasibility prototype."""
import sqlite3
from pathlib import Path

SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value INTEGER NOT NULL);
INSERT OR IGNORE INTO meta VALUES ('timetable_revision', 0);
CREATE TABLE IF NOT EXISTS events (
    source_key TEXT PRIMARY KEY, course_code TEXT NOT NULL, course_title TEXT NOT NULL,
    date TEXT NOT NULL, start_time TEXT NOT NULL, end_time TEXT NOT NULL,
    room TEXT NOT NULL DEFAULT '', teacher TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS previews (
    token TEXT PRIMARY KEY, rows_json TEXT NOT NULL, revision INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS import_batches (
    id INTEGER PRIMARY KEY, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    added INTEGER NOT NULL, updated INTEGER NOT NULL, unchanged INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY, date TEXT NOT NULL, kind TEXT NOT NULL,
    context TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL,
    status TEXT NOT NULL, event_key TEXT REFERENCES events(source_key),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY, week TEXT NOT NULL, title TEXT NOT NULL,
    snapshot_json TEXT NOT NULL, pdf BLOB NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


class Connection(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


def connect(path):
    db = sqlite3.connect(path, timeout=10, factory=Connection)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    return db


def initialize(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with connect(path) as db:
        db.executescript(SCHEMA)
