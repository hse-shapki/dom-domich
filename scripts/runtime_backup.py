"""Backup/verify/restore PostgreSQL и FileStore; restore требует пустую цель."""

import argparse
import hashlib
import json
import subprocess
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _database_name(database_url: str) -> str:
    name = urlsplit(database_url.replace("postgresql+asyncpg://", "postgresql://", 1)).path.lstrip(
        "/"
    )
    if not name or "/" in name:
        raise ValueError("DATABASE_URL must identify one database")
    return name


def create_backup(database_url: str, file_store: Path, output: Path) -> Path:
    if not file_store.is_dir():
        raise ValueError("FileStore directory does not exist")
    output.mkdir(parents=True, exist_ok=False)
    database_dump = output / "postgres.dump"
    files_archive = output / "files.tar.gz"
    pg_url = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    subprocess.run(
        ["pg_dump", "--format=custom", "--file", str(database_dump), "--dbname", pg_url],
        check=True,
    )
    with tarfile.open(files_archive, "w:gz") as archive:
        archive.add(file_store, arcname="files")
    manifest = {
        "created_at": datetime.now(UTC).isoformat(),
        "database_name": _database_name(database_url),
        "files": {
            database_dump.name: sha256_file(database_dump),
            files_archive.name: sha256_file(files_archive),
        },
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return output


def verify_backup(backup: Path) -> dict[str, object]:
    manifest = json.loads((backup / "manifest.json").read_text(encoding="utf-8"))
    files = manifest.get("files")
    if not isinstance(files, dict):
        raise ValueError("backup manifest has no files")
    for name, expected in files.items():
        if not isinstance(name, str) or not isinstance(expected, str):
            raise ValueError("invalid backup manifest entry")
        path = backup / name
        if not path.is_file() or sha256_file(path) != expected:
            raise ValueError(f"backup checksum mismatch: {name}")
    return manifest


def restore_backup(database_url: str, backup: Path, file_store: Path) -> None:
    verify_backup(backup)
    database_name = _database_name(database_url)
    if not database_name.endswith("_restore_test"):
        raise ValueError("restore is limited to a database ending in _restore_test")
    if file_store.exists() and any(file_store.iterdir()):
        raise ValueError("restore FileStore target must be empty")
    file_store.mkdir(parents=True, exist_ok=True)
    pg_url = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    subprocess.run(
        [
            "pg_restore",
            "--exit-on-error",
            "--no-owner",
            "--dbname",
            pg_url,
            str(backup / "postgres.dump"),
        ],
        check=True,
    )
    with tempfile.TemporaryDirectory() as temporary:
        temporary_path = Path(temporary)
        with tarfile.open(backup / "files.tar.gz", "r:gz") as archive:
            archive.extractall(temporary_path, filter="data")
        restored = temporary_path / "files"
        if not restored.is_dir():
            raise ValueError("FileStore archive has invalid root")
        for source in restored.rglob("*"):
            if source.is_file():
                target = file_store / source.relative_to(restored)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(source.read_bytes())


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    backup = subparsers.add_parser("backup")
    backup.add_argument("--database-url", required=True)
    backup.add_argument("--file-store", type=Path, required=True)
    backup.add_argument("--output", type=Path, required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--backup", type=Path, required=True)
    restore = subparsers.add_parser("restore")
    restore.add_argument("--database-url", required=True)
    restore.add_argument("--backup", type=Path, required=True)
    restore.add_argument("--file-store", type=Path, required=True)
    arguments = parser.parse_args()
    if arguments.command == "backup":
        create_backup(arguments.database_url, arguments.file_store, arguments.output)
    elif arguments.command == "verify":
        verify_backup(arguments.backup)
    else:
        restore_backup(arguments.database_url, arguments.backup, arguments.file_store)


if __name__ == "__main__":
    main()
