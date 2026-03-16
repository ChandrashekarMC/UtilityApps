import os
from pathlib import Path
import sqlite3


def get_db_path() -> str:
    explicit_db_path = os.getenv("DB_PATH", "").strip()
    if explicit_db_path:
        return explicit_db_path

    data_dir = os.getenv("APP_DATA_DIR", "").strip()
    if data_dir:
        Path(data_dir).mkdir(parents=True, exist_ok=True)
        return str(Path(data_dir) / "tasks.db")

    return "tasks.db"


def get_connection():
    conn = sqlite3.connect(get_db_path(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_column(cur, table, column, definition):
    cur.execute(f"PRAGMA table_info({table})")
    existing_columns = {row[1] for row in cur.fetchall()}
    if column not in existing_columns:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def init_db():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
    CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        task_id TEXT UNIQUE,
        category TEXT,
        due_date DATE,
        priority TEXT,
        urgency TEXT,
        progress INTEGER,
        parent_task_id TEXT,
        status TEXT DEFAULT 'active',
        starred BOOLEAN DEFAULT 0,
        notes TEXT,
        attachment_path TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        completed_at TIMESTAMP,
        archived_at TIMESTAMP
    )
    """
    )

    _ensure_column(cur, "tasks", "parent_task_id", "TEXT")
    _ensure_column(cur, "tasks", "starred", "BOOLEAN DEFAULT 0")
    _ensure_column(cur, "tasks", "created_at", "TIMESTAMP")
    _ensure_column(cur, "tasks", "completed_at", "TIMESTAMP")
    _ensure_column(cur, "tasks", "archived_at", "TIMESTAMP")

    cur.execute(
        """
    CREATE TABLE IF NOT EXISTS recurring_rules (
        task_id TEXT,
        frequency_type TEXT,
        interval_x INTEGER,
        interval_y INTEGER,
        weekdays TEXT,
        end_type TEXT,
        end_date DATE,
        occurrence_count INTEGER
    )
    """
    )

    cur.execute(
        """
    CREATE TABLE IF NOT EXISTS reminders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id TEXT,
        reminder_offset_minutes INTEGER,
        sound TEXT,
        volume INTEGER,
        snooze BOOLEAN
    )
    """
    )

    cur.execute(
        """
    CREATE TABLE IF NOT EXISTS task_notes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id TEXT,
        note_text TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """
    )

    cur.execute(
        """
    CREATE TABLE IF NOT EXISTS categories (
        name TEXT PRIMARY KEY,
        is_default BOOLEAN
    )
    """
    )

    cur.execute(
        """
    CREATE TABLE IF NOT EXISTS app_meta (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    """
    )

    # Insert default categories
    defaults = ["Personal", "Official", "Wishlist", "Birthday"]
    for cat in defaults:
        cur.execute("INSERT OR IGNORE INTO categories VALUES (?, 1)", (cat,))

    cur.execute("UPDATE categories SET is_default=0 WHERE name IN ('All', 'cat2')")

    conn.commit()
    conn.close()
