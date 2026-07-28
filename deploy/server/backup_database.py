#!/usr/bin/env python3
"""Create a credential-safe pre-deployment database backup."""

from __future__ import annotations

import argparse
import gzip
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime

from dotenv import dotenv_values
from sqlalchemy.engine import make_url


SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--backup-dir", type=Path, required=True)
    parser.add_argument("--sha", required=True)
    return parser.parse_args()


def backup_mysql(database_url: str, target: Path) -> None:
    url = make_url(database_url)
    if not url.database:
        raise RuntimeError("DATABASE_URL does not name a database")

    command = [
        "mysqldump",
        "--single-transaction",
        "--quick",
        "--routines",
        "--triggers",
        "--events",
        "--hex-blob",
        "--default-character-set=utf8mb4",
    ]
    if url.host:
        command.extend(["--host", url.host])
    if url.port:
        command.extend(["--port", str(url.port)])
    if url.username:
        command.extend(["--user", url.username])
    command.append(url.database)

    process_env = os.environ.copy()
    if url.password:
        process_env["MYSQL_PWD"] = url.password

    temporary = target.with_suffix(target.suffix + ".tmp")
    try:
        with gzip.open(temporary, "wb", compresslevel=6) as output:
            result = subprocess.run(
                command,
                stdout=output,
                stderr=subprocess.DEVNULL,
                env=process_env,
                check=False,
            )
        if result.returncode != 0:
            raise RuntimeError(f"mysqldump failed with exit code {result.returncode}")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def backup_sqlite(database_url: str, target: Path) -> None:
    url = make_url(database_url)
    source = Path(url.database or "").expanduser().resolve()
    if not source.is_file():
        raise RuntimeError("SQLite database file does not exist")
    temporary = target.with_suffix(".db.tmp")
    try:
        shutil.copy2(source, temporary)
        os.replace(temporary, target.with_suffix(".db"))
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    args = parse_args()
    if not SHA_PATTERN.fullmatch(args.sha):
        raise RuntimeError("invalid deployment SHA")

    config = dotenv_values(args.env_file)
    database_url = config.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is missing from the production environment")

    args.backup_dir.mkdir(mode=0o750, parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    target = args.backup_dir / f"haorizi-{timestamp}-{args.sha}.sql.gz"
    backend = make_url(database_url).get_backend_name()

    if backend == "mysql":
        backup_mysql(database_url, target)
    elif backend == "sqlite":
        backup_sqlite(database_url, target)
        target = target.with_suffix(".db")
    else:
        raise RuntimeError(f"unsupported database backend: {backend}")

    print(f"database backup created: {target.name}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # keep credentials and connection strings out of logs
        print(f"database backup failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
