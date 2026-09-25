"""Постоянное локальное хранилище evidence/PDF с привязкой к дому и hash."""

import asyncio
import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Protocol
from uuid import UUID, uuid4


class FileKind(StrEnum):
    EVIDENCE = "evidence"
    DOCUMENT = "document"


class FileStoreError(Exception):
    """Базовая ошибка хранения файла."""


class FileTooLarge(FileStoreError):
    """Файл больше настроенного безопасного предела."""


class UnsupportedMime(FileStoreError):
    """MIME не разрешён для этого вида файла."""


class StoredFileNotFound(FileStoreError):
    """Файл не найден в пространстве данного дома."""


class FileIntegrityError(FileStoreError):
    """Содержимое или метаданные не совпадают с записанным hash."""


class Clock(Protocol):
    def now(self) -> datetime: ...


@dataclass(frozen=True, slots=True)
class StoredFile:
    file_key: UUID
    house_id: UUID
    kind: FileKind
    mime_type: str
    size_bytes: int
    sha256: str
    created_at: datetime
    retain_until: datetime | None


_ALLOWED_MIME = {
    FileKind.EVIDENCE: frozenset({"image/jpeg", "image/png", "image/webp"}),
    FileKind.DOCUMENT: frozenset({"application/pdf"}),
}
_DEMO_RETENTION = timedelta(days=30)


def _require_utc(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{name} must use UTC")


def _matches_signature(mime_type: str, content: bytes) -> bool:
    if mime_type == "application/pdf":
        return content.startswith(b"%PDF-")
    if mime_type == "image/jpeg":
        return content.startswith(b"\xff\xd8\xff")
    if mime_type == "image/png":
        return content.startswith(b"\x89PNG\r\n\x1a\n")
    if mime_type == "image/webp":
        return content.startswith(b"RIFF") and content[8:12] == b"WEBP"
    return False


class LocalFileStore:
    """File key всегда UUID; имя файла пользователя не участвует в построении пути."""

    def __init__(self, root: Path, clock: Clock, *, max_size_bytes: int = 20_000_000) -> None:
        if max_size_bytes <= 0:
            raise ValueError("max_size_bytes must be positive")
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.root = root.resolve()
        self.clock = clock
        self.max_size_bytes = max_size_bytes

    async def put(
        self,
        house_id: UUID,
        kind: FileKind,
        mime_type: str,
        content: bytes,
        *,
        retain_until: datetime | None = None,
    ) -> StoredFile:
        if mime_type not in _ALLOWED_MIME[kind]:
            raise UnsupportedMime(mime_type)
        if not content or len(content) > self.max_size_bytes:
            raise FileTooLarge("file is empty or exceeds size limit")
        if not _matches_signature(mime_type, content):
            raise UnsupportedMime("file content does not match declared MIME")
        created_at = self.clock.now()
        _require_utc(created_at, "created_at")
        retain_until = retain_until or created_at + _DEMO_RETENTION
        _require_utc(retain_until, "retain_until")
        if retain_until <= created_at:
            raise ValueError("retain_until must be in the future")
        stored = StoredFile(
            file_key=uuid4(),
            house_id=house_id,
            kind=kind,
            mime_type=mime_type,
            size_bytes=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            created_at=created_at,
            retain_until=retain_until,
        )
        await asyncio.to_thread(self._put_sync, stored, content)
        return stored

    async def get(self, house_id: UUID, file_key: UUID) -> tuple[StoredFile, bytes]:
        return await asyncio.to_thread(self._get_sync, house_id, file_key)

    async def delete(self, house_id: UUID, file_key: UUID) -> None:
        await asyncio.to_thread(self._delete_sync, house_id, file_key)

    async def purge_expired(self, house_id: UUID, now: datetime) -> int:
        """Удаляет только файлы заданного дома; вызывается отдельной durable job."""

        _require_utc(now, "now")
        return await asyncio.to_thread(self._purge_expired_sync, house_id, now)

    def _paths(self, house_id: UUID, file_key: UUID) -> tuple[Path, Path]:
        folder = self.root / str(house_id) / file_key.hex[:2]
        if not folder.resolve().is_relative_to(self.root):
            raise FileIntegrityError("file path escaped storage root")
        return folder / f"{file_key}.bin", folder / f"{file_key}.json"

    def _put_sync(self, stored: StoredFile, content: bytes) -> None:
        blob_path, meta_path = self._paths(stored.house_id, stored.file_key)
        blob_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        metadata = {
            "file_key": str(stored.file_key),
            "house_id": str(stored.house_id),
            "kind": stored.kind.value,
            "mime_type": stored.mime_type,
            "size_bytes": stored.size_bytes,
            "sha256": stored.sha256,
            "created_at": stored.created_at.isoformat(),
            "retain_until": stored.retain_until.isoformat() if stored.retain_until else None,
        }
        self._atomic_write(blob_path, content)
        try:
            self._atomic_write(meta_path, json.dumps(metadata, sort_keys=True).encode("utf-8"))
        except OSError:
            blob_path.unlink(missing_ok=True)
            raise

    @staticmethod
    def _atomic_write(path: Path, content: bytes) -> None:
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
                temp_path = Path(temporary.name)
                temporary.write(content)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temp_path, path)
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    def _get_sync(self, house_id: UUID, file_key: UUID) -> tuple[StoredFile, bytes]:
        blob_path, meta_path = self._paths(house_id, file_key)
        if blob_path.is_symlink() or meta_path.is_symlink():
            raise FileIntegrityError("symbolic links are not allowed in file storage")
        try:
            raw = json.loads(meta_path.read_text(encoding="utf-8"))
        except FileNotFoundError as error:
            raise StoredFileNotFound("file is not available for this house") from error
        except (ValueError, UnicodeError) as error:
            raise FileIntegrityError("invalid file metadata") from error
        try:
            stored = StoredFile(
                file_key=UUID(raw["file_key"]),
                house_id=UUID(raw["house_id"]),
                kind=FileKind(raw["kind"]),
                mime_type=str(raw["mime_type"]),
                size_bytes=int(raw["size_bytes"]),
                sha256=str(raw["sha256"]),
                created_at=datetime.fromisoformat(raw["created_at"]),
                retain_until=(
                    datetime.fromisoformat(raw["retain_until"])
                    if raw["retain_until"] is not None
                    else None
                ),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise FileIntegrityError("invalid file metadata fields") from error
        if stored.house_id != house_id or stored.file_key != file_key:
            raise FileIntegrityError("file ownership metadata mismatch")
        try:
            _require_utc(stored.created_at, "created_at")
            if stored.retain_until is None:
                raise ValueError("retain_until is missing")
            _require_utc(stored.retain_until, "retain_until")
        except ValueError as error:
            raise FileIntegrityError("invalid file timestamps") from error
        if stored.mime_type not in _ALLOWED_MIME[stored.kind] or stored.size_bytes <= 0:
            raise FileIntegrityError("invalid file metadata type or size")
        if stored.size_bytes > self.max_size_bytes:
            raise FileIntegrityError("file exceeds configured size limit")
        try:
            if blob_path.stat().st_size > self.max_size_bytes:
                raise FileIntegrityError("file exceeds configured size limit")
            content = blob_path.read_bytes()
        except FileNotFoundError as error:
            raise FileIntegrityError("file content is missing") from error
        if (
            len(content) != stored.size_bytes
            or hashlib.sha256(content).hexdigest() != stored.sha256
            or not _matches_signature(stored.mime_type, content)
        ):
            raise FileIntegrityError("file content checksum mismatch")
        return stored, content

    def _delete_sync(self, house_id: UUID, file_key: UUID) -> None:
        self._get_sync(house_id, file_key)
        blob_path, meta_path = self._paths(house_id, file_key)
        meta_path.unlink()
        blob_path.unlink(missing_ok=True)

    def _purge_expired_sync(self, house_id: UUID, now: datetime) -> int:
        house_folder = self.root / str(house_id)
        if not house_folder.exists():
            return 0
        removed = 0
        for meta_path in house_folder.glob("*/*.json"):
            try:
                file_key = UUID(meta_path.stem)
            except ValueError as error:
                raise FileIntegrityError("invalid metadata file name") from error
            stored, _ = self._get_sync(house_id, file_key)
            if stored.retain_until is not None and stored.retain_until <= now:
                self._delete_sync(house_id, file_key)
                removed += 1
        return removed
