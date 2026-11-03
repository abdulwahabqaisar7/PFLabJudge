"""Tests for CPJudge database backup and restore utility."""
import sqlite3
import pytest

from cpjudge.utils.backup import backup_sqlite, list_backups, restore_sqlite


def test_sqlite_hot_backup_and_restore(tmp_path):
    # Create test SQLite database with a sample table and row
    db_file = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_file))
    with conn:
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT);")
        conn.execute("INSERT INTO users (name) VALUES ('Ada Lovelace');")
    conn.close()

    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()

    # Create backup
    backup_file = backup_sqlite(db_file, output_dir=backup_dir)
    assert backup_file.exists()
    assert backup_file.stat().st_size > 0

    # Mutate original database
    conn = sqlite3.connect(str(db_file))
    with conn:
        conn.execute("INSERT INTO users (name) VALUES ('Charles Babbage');")
        rows = conn.execute("SELECT COUNT(*) FROM users;").fetchone()[0]
        assert rows == 2
    conn.close()

    # Restore from backup
    restore_sqlite(backup_file, db_file)

    # Verify restored state
    conn = sqlite3.connect(str(db_file))
    with conn:
        rows = conn.execute("SELECT name FROM users;").fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "Ada Lovelace"
    conn.close()
