import os
import sqlite3
from datetime import datetime, timezone

from flask import current_app, g

SCHEMA = """
CREATE TABLE IF NOT EXISTS members (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    avatar TEXT,
    is_admin INTEGER NOT NULL DEFAULT 0,
    voting_active INTEGER NOT NULL DEFAULT 1,
    in_wheel_pool INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS login_codes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    code TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_at TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS rounds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    state TEXT NOT NULL DEFAULT 'spin',
    chooser_id INTEGER REFERENCES members(id) ON DELETE SET NULL,
    winner_candidate_id INTEGER,
    meeting_date TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS book_candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    round_id INTEGER NOT NULL REFERENCES rounds(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    author TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS votes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    round_id INTEGER NOT NULL REFERENCES rounds(id) ON DELETE CASCADE,
    candidate_id INTEGER NOT NULL REFERENCES book_candidates(id) ON DELETE CASCADE,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    weight REAL NOT NULL DEFAULT 1.0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(round_id, member_id)
);

CREATE TABLE IF NOT EXISTS read_marks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    round_id INTEGER NOT NULL REFERENCES rounds(id) ON DELETE CASCADE,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    has_read INTEGER NOT NULL,
    marked_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(round_id, member_id)
);

CREATE TABLE IF NOT EXISTS past_books (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    author TEXT NOT NULL DEFAULT '',
    read_date TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS past_book_readers (
    past_book_id INTEGER NOT NULL REFERENCES past_books(id) ON DELETE CASCADE,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    PRIMARY KEY (past_book_id, member_id)
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def get_db():
    if "db" not in g:
        db = sqlite3.connect(current_app.config["DATABASE_PATH"], timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("PRAGMA journal_mode = WAL")
        db.execute("PRAGMA busy_timeout = 5000")
        g.db = db
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def _migration_003_wheel_suspended(db):
    cols = {row[1] for row in db.execute("PRAGMA table_info(members)")}
    if "wheel_suspended" not in cols:
        db.execute("ALTER TABLE members ADD COLUMN wheel_suspended INTEGER NOT NULL DEFAULT 0")


MIGRATIONS = [
    ("001_base", SCHEMA),
    (
        "002_audit_log",
        """
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL DEFAULT (datetime('now')),
            actor_id INTEGER REFERENCES members(id) ON DELETE SET NULL,
            action TEXT NOT NULL,
            details TEXT NOT NULL DEFAULT ''
        );
        """,
    ),
    ("003_wheel_suspended", _migration_003_wheel_suspended),
]


def audit(actor_id, action, details=""):
    execute("INSERT INTO audit_log(actor_id, action, details) VALUES (?, ?, ?)", (actor_id, action, details))

BACKUP_KEEP = 50


def backup_database(db_path, backup_dir, keep=BACKUP_KEEP):
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest_path = backup_dir / f"bokklubben-{stamp}.db"
    src = sqlite3.connect(db_path, timeout=10)
    dest = sqlite3.connect(str(dest_path))
    try:
        src.backup(dest)
    finally:
        dest.close()
        src.close()
    files = sorted(backup_dir.glob("bokklubben-*.db"))
    if keep:
        for old in files[:-keep]:
            try:
                old.unlink()
            except OSError:
                pass
    return dest_path


def init_db(app):
    db_path = app.config["DATABASE_PATH"]
    if os.path.exists(db_path):
        try:
            backup_database(db_path, app.config["DATA_DIR"] / "backups")
        except Exception:
            pass
    db = sqlite3.connect(db_path, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "version TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    applied = {r["version"] for r in db.execute("SELECT version FROM schema_migrations")}
    for version, sql in MIGRATIONS:
        if version not in applied:
            if callable(sql):
                sql(db)
            else:
                db.executescript(sql)
            db.execute("INSERT INTO schema_migrations(version) VALUES (?)", (version,))
    db.execute("INSERT OR IGNORE INTO settings(key, value) VALUES ('club_name', 'Bokklubben')")
    has_members = db.execute("SELECT COUNT(*) AS c FROM members").fetchone()["c"] > 0
    has_rounds = db.execute("SELECT COUNT(*) AS c FROM rounds").fetchone()["c"] > 0
    if has_members and not has_rounds:
        db.execute("INSERT INTO rounds(state) VALUES ('spin')")
    db.commit()
    db.close()


def query(sql, params=()):
    return get_db().execute(sql, params).fetchall()


def one(sql, params=()):
    return get_db().execute(sql, params).fetchone()


def execute(sql, params=()):
    db = get_db()
    cur = db.execute(sql, params)
    db.commit()
    return cur.lastrowid
