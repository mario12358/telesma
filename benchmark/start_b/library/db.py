"""SQLite connection and schema migrations."""

import sqlite3
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
ROLLBACK_SUFFIX = ".down.sql"


def open_db(path: Path | str) -> sqlite3.Connection:
    # Requests are handled by server threads; access to the connection is serialised by the Application lock.
    connection = sqlite3.connect(path, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    apply_migrations(connection)
    return connection


def apply_migrations(connection: sqlite3.Connection) -> None:
    connection.execute(
        "CREATE TABLE IF NOT EXISTS migrations (version TEXT PRIMARY KEY)"
    )
    applied = {
        row["version"] for row in connection.execute("SELECT version FROM migrations")
    }
    for file in _migration_files():
        if file.stem in applied:
            continue
        # The scripts are idempotent, so an interruption before the version is recorded is safe.
        connection.executescript(file.read_text(encoding="utf-8"))
        connection.execute("INSERT INTO migrations (version) VALUES (?)", (file.stem,))
        connection.commit()


def _migration_files() -> list[Path]:
    return sorted(
        file
        for file in MIGRATIONS_DIR.glob("*.sql")
        if not file.name.endswith(ROLLBACK_SUFFIX)
    )
