from pathlib import Path

import pytest

from scripts.runtime_backup import _database_name, sha256_file, verify_backup


def test_backup_verification_detects_changed_file(tmp_path: Path) -> None:
    payload = tmp_path / "postgres.dump"
    payload.write_bytes(b"backup")
    (tmp_path / "manifest.json").write_text(
        '{"files":{"postgres.dump":"' + sha256_file(payload) + '"}}', encoding="utf-8"
    )
    assert verify_backup(tmp_path)["files"]

    payload.write_bytes(b"changed")
    with pytest.raises(ValueError, match="checksum"):
        verify_backup(tmp_path)


def test_restore_database_name_must_be_explicit() -> None:
    assert _database_name("postgresql+asyncpg://user:pass@db/app_restore_test") == (
        "app_restore_test"
    )
