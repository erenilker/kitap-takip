import os
import sqlite3


DB_PATH = os.getenv("DB_PATH", os.path.join("data", "kitap.db"))


def get_db():
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db():
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    connection = get_db()
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS books (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            author TEXT NOT NULL,
            publisher TEXT,
            cover_path TEXT,
            product_url TEXT,
            pages INTEGER,
            isbn TEXT,
            publication_year TEXT,
            status TEXT NOT NULL DEFAULT 'okunacak',
            rating INTEGER DEFAULT 0,
            note TEXT,
            finished_at TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS reading_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id INTEGER NOT NULL,
            log_date TEXT NOT NULL,
            current_page INTEGER NOT NULL,
            pages_added INTEGER NOT NULL,
            FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_books_unique
        ON books(lower(trim(title)), lower(trim(author)));
        """
    )
    connection.execute(
        "INSERT OR IGNORE INTO settings(key, value) VALUES ('yearly_goal', '24')"
    )
    connection.commit()
    connection.close()


def get_setting(key, default=None):
    connection = get_db()
    row = connection.execute(
        "SELECT value FROM settings WHERE key = ?", (key,)
    ).fetchone()
    connection.close()
    return row["value"] if row else default


def set_setting(key, value):
    connection = get_db()
    connection.execute(
        "INSERT INTO settings(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, str(value)),
    )
    connection.commit()
    connection.close()
