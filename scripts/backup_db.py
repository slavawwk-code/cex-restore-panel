#!/usr/bin/env python3
import os
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

def main() -> int:
    try:
        from app.config import ensure_runtime_directories, load_settings

        settings = load_settings(require_secrets=False)
        ensure_runtime_directories(settings)
        if settings.database_path is None:
            raise RuntimeError("in-memory databases cannot be backed up")
        if not settings.database_path.is_file():
            raise FileNotFoundError(settings.database_path)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        destination = settings.backup_dir / f"backup_{timestamp}"
        temporary = settings.backup_dir / f".backup_{timestamp}.incomplete"
        temporary.mkdir(mode=0o700)

        _sqlite_backup(settings.database_path, temporary / "cex_restore.db")
        session_backup_dir = temporary / "sessions"
        session_backup_dir.mkdir(mode=0o700)
        for session_file in settings.sessions_dir.glob("*.session"):
            _sqlite_backup(session_file, session_backup_dir / session_file.name)

        if settings.env_file.is_file():
            env_backup = temporary / ".env.backup"
            shutil.copy2(settings.env_file, env_backup)
            os.chmod(env_backup, 0o600)
        os.replace(temporary, destination)
    except Exception as error:
        print(f"Backup failed: {type(error).__name__}: {error}", file=sys.stderr)
        return 1

    print(destination)
    return 0


def _sqlite_backup(source_path: Path, destination_path: Path) -> None:
    with sqlite3.connect(source_path) as source:
        with sqlite3.connect(destination_path) as target:
            source.backup(target)
    os.chmod(destination_path, 0o600)


if __name__ == "__main__":
    raise SystemExit(main())
