"""Database backup and restore utilities for CPJudge.

Supports SQLite hot transactional backups via sqlite3.Connection.backup()
as well as PostgreSQL dumps via pg_dump when configured.
"""
from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys

from cpjudge.config import BASE_DIR, Config
from cpjudge.utils.timezone import format_pkt, now_pkt


def get_backup_dir() -> Path:
    """Returns the directory where database backups are stored."""
    backup_dir = BASE_DIR / "instance" / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    return backup_dir


def backup_sqlite(db_path: Path, output_dir: Path | None = None) -> Path:
    """Performs an online, transactionally consistent hot backup of an SQLite database.

    Uses the SQLite Online Backup API (connection.backup) which locks pages safely
    without stopping concurrent web or judge worker operations.
    """
    if not db_path.exists():
        raise FileNotFoundError(f"Source database file not found at: {db_path}")

    if output_dir is None:
        output_dir = get_backup_dir()

    timestamp = now_pkt().strftime("%Y%m%d_%H%M%S")
    target_path = output_dir / f"cpjudge_backup_{timestamp}.db"

    # Perform hot backup via sqlite3.Connection.backup
    src_conn = sqlite3.connect(str(db_path))
    dest_conn = sqlite3.connect(str(target_path))
    try:
        with dest_conn:
            src_conn.backup(dest_conn, pages=100)
    finally:
        dest_conn.close()
        src_conn.close()

    return target_path


def backup_postgres(db_url: str, output_dir: Path | None = None) -> Path:
    """Performs a PostgreSQL backup using pg_dump."""
    if output_dir is None:
        output_dir = get_backup_dir()

    timestamp = now_pkt().strftime("%Y%m%d_%H%M%S")
    target_path = output_dir / f"cpjudge_pg_backup_{timestamp}.sql"

    cmd = ["pg_dump", "--dbname", db_url, "-f", str(target_path)]
    subprocess.run(cmd, check=True)
    return target_path


def run_backup() -> Path:
    """Detects database backend from configuration and runs the appropriate backup."""
    db_uri = Config.SQLALCHEMY_DATABASE_URI
    if db_uri.startswith("sqlite:///"):
        sqlite_file = Path(db_uri.replace("sqlite:///", ""))
        return backup_sqlite(sqlite_file)
    elif db_uri.startswith("postgresql://") or db_uri.startswith("postgres://"):
        return backup_postgres(db_uri)
    else:
        raise ValueError(f"Unsupported database URI scheme: {db_uri}")


def restore_sqlite(backup_file: Path, db_path: Path) -> Path:
    """Restores an SQLite database from a backup file after creating a pre-restore safety snapshot."""
    if not backup_file.exists():
        raise FileNotFoundError(f"Backup file not found at: {backup_file}")

    # Create safety snapshot of current active DB if it exists
    if db_path.exists():
        safety_path = db_path.with_name(f"{db_path.name}.pre_restore_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}")
        shutil.copy2(db_path, safety_path)

    # Use hot restore
    src_conn = sqlite3.connect(str(backup_file))
    dest_conn = sqlite3.connect(str(db_path))
    try:
        with dest_conn:
            src_conn.backup(dest_conn, pages=100)
    finally:
        dest_conn.close()
        src_conn.close()

    return db_path


def list_backups() -> list[dict]:
    """Returns a list of available backups with timestamps and file sizes."""
    backup_dir = get_backup_dir()
    backups = []
    for f in sorted(backup_dir.glob("cpjudge_*"), reverse=True):
        if f.is_file():
            stat = f.stat()
            backups.append({
                "path": str(f),
                "name": f.name,
                "size_bytes": stat.st_size,
                "size_kb": round(stat.st_size / 1024, 1),
                "modified": format_pkt(datetime.fromtimestamp(stat.st_mtime, timezone.utc), "%Y-%m-%d %H:%M:%S PKT"),
            })
    return backups


def main():
    import argparse

    parser = argparse.ArgumentParser(description="CPJudge Database Backup & Restore Utility")
    parser.add_argument("--backup", action="store_true", help="Create a new hot database backup")
    parser.add_argument("--list", action="store_true", help="List all existing backups")
    parser.add_argument("--restore", type=str, help="Path to backup file to restore")

    args = parser.parse_args()

    if args.backup:
        try:
            target = run_backup()
            print(f"[SUCCESS] Database backup created at: {target}")
            print(f"Size: {target.stat().st_size:,} bytes")
        except Exception as e:
            print(f"[ERROR] Backup failed: {e}", file=sys.stderr)
            sys.exit(1)

    elif args.list:
        backups = list_backups()
        if not backups:
            print("No backups found in instance/backups/.")
        else:
            print(f"Found {len(backups)} backup(s):")
            for b in backups:
                print(f"  - {b['name']} ({b['size_kb']} KB, {b['modified']})")

    elif args.restore:
        target_file = Path(args.restore)
        db_uri = Config.SQLALCHEMY_DATABASE_URI
        if db_uri.startswith("sqlite:///"):
            active_db = Path(db_uri.replace("sqlite:///", ""))
            try:
                restore_sqlite(target_file, active_db)
                print(f"[SUCCESS] Restored {active_db} from {target_file}")
            except Exception as e:
                print(f"[ERROR] Restore failed: {e}", file=sys.stderr)
                sys.exit(1)
        else:
            print("[NOTICE] For PostgreSQL, restore using: psql <database_url> < backup.sql")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
