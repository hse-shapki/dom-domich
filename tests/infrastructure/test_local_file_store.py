import asyncio
import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from dom_domych.infrastructure.files.local import (
    FileIntegrityError,
    FileKind,
    FileTooLarge,
    LocalFileStore,
    StoredFileNotFound,
    UnsupportedMime,
)
from tests.fixtures.zamira_house import HOUSE_ONE, HOUSE_TWO

PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF"
PNG = b"\x89PNG\r\n\x1a\n" + b"demo-image-content"


class FakeClock:
    def now(self) -> datetime:
        return datetime(2026, 9, 25, 12, tzinfo=UTC)


@pytest.mark.asyncio
async def test_put_and_get_pdf_uses_private_key_hash_and_default_retention(
    tmp_path: Path,
) -> None:
    store = LocalFileStore(tmp_path, FakeClock())

    meta = await store.put(HOUSE_ONE, FileKind.DOCUMENT, "application/pdf", PDF)
    loaded_meta, content = await store.get(HOUSE_ONE, meta.file_key)

    assert content == PDF
    assert loaded_meta == meta
    assert meta.sha256 == hashlib.sha256(PDF).hexdigest()
    assert meta.retain_until == FakeClock().now() + timedelta(days=30)
    assert (tmp_path / str(HOUSE_ONE) / meta.file_key.hex[:2] / f"{meta.file_key}.bin").exists()


@pytest.mark.asyncio
async def test_other_house_cannot_read_or_delete_file(tmp_path: Path) -> None:
    store = LocalFileStore(tmp_path, FakeClock())
    meta = await store.put(HOUSE_ONE, FileKind.EVIDENCE, "image/png", PNG)

    with pytest.raises(StoredFileNotFound):
        await store.get(HOUSE_TWO, meta.file_key)
    with pytest.raises(StoredFileNotFound):
        await store.delete(HOUSE_TWO, meta.file_key)

    assert (await store.get(HOUSE_ONE, meta.file_key))[1] == PNG


@pytest.mark.asyncio
async def test_rejects_oversize_unsupported_and_false_mime(tmp_path: Path) -> None:
    store = LocalFileStore(tmp_path, FakeClock(), max_size_bytes=len(PNG))

    with pytest.raises(FileTooLarge):
        await store.put(HOUSE_ONE, FileKind.EVIDENCE, "image/png", PNG + b"extra")
    with pytest.raises(UnsupportedMime):
        await store.put(HOUSE_ONE, FileKind.EVIDENCE, "text/plain", b"private text")
    with pytest.raises(UnsupportedMime, match="does not match"):
        await store.put(HOUSE_ONE, FileKind.EVIDENCE, "image/png", b"not actually png")
    with pytest.raises(UnsupportedMime):
        await store.put(HOUSE_ONE, FileKind.DOCUMENT, "image/png", PNG)


@pytest.mark.asyncio
async def test_tampered_content_and_symlink_are_not_served(tmp_path: Path) -> None:
    store = LocalFileStore(tmp_path, FakeClock())
    first = await store.put(HOUSE_ONE, FileKind.DOCUMENT, "application/pdf", PDF)
    first_path = tmp_path / str(HOUSE_ONE) / first.file_key.hex[:2] / f"{first.file_key}.bin"
    first_path.write_bytes(PDF + b"tampered")

    with pytest.raises(FileIntegrityError, match="checksum"):
        await store.get(HOUSE_ONE, first.file_key)

    second = await store.put(HOUSE_ONE, FileKind.DOCUMENT, "application/pdf", PDF)
    second_path = tmp_path / str(HOUSE_ONE) / second.file_key.hex[:2] / f"{second.file_key}.bin"
    second_path.unlink()
    second_path.symlink_to(first_path)
    with pytest.raises(FileIntegrityError, match="symbolic links"):
        await store.get(HOUSE_ONE, second.file_key)


@pytest.mark.asyncio
async def test_tampered_ownership_metadata_is_not_served(tmp_path: Path) -> None:
    store = LocalFileStore(tmp_path, FakeClock())
    stored = await store.put(HOUSE_ONE, FileKind.DOCUMENT, "application/pdf", PDF)
    meta_path = tmp_path / str(HOUSE_ONE) / stored.file_key.hex[:2] / f"{stored.file_key}.json"
    metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    metadata["house_id"] = str(HOUSE_TWO)
    meta_path.write_text(json.dumps(metadata), encoding="utf-8")

    with pytest.raises(FileIntegrityError, match="ownership"):
        await store.get(HOUSE_ONE, stored.file_key)


@pytest.mark.asyncio
async def test_delete_removes_file_from_house_space(tmp_path: Path) -> None:
    store = LocalFileStore(tmp_path, FakeClock())
    stored = await store.put(HOUSE_ONE, FileKind.DOCUMENT, "application/pdf", PDF)

    await store.delete(HOUSE_ONE, stored.file_key)

    with pytest.raises(StoredFileNotFound):
        await store.get(HOUSE_ONE, stored.file_key)


@pytest.mark.asyncio
async def test_expired_files_are_purged_only_in_selected_house(tmp_path: Path) -> None:
    store = LocalFileStore(tmp_path, FakeClock())
    short = await store.put(
        HOUSE_ONE,
        FileKind.EVIDENCE,
        "image/png",
        PNG,
        retain_until=FakeClock().now() + timedelta(hours=1),
    )
    retained = await store.put(HOUSE_ONE, FileKind.DOCUMENT, "application/pdf", PDF)
    other_house = await store.put(
        HOUSE_TWO,
        FileKind.EVIDENCE,
        "image/png",
        PNG,
        retain_until=FakeClock().now() + timedelta(hours=1),
    )

    count = await store.purge_expired(HOUSE_ONE, FakeClock().now() + timedelta(hours=2))

    assert count == 1
    with pytest.raises(StoredFileNotFound):
        await store.get(HOUSE_ONE, short.file_key)
    assert (await store.get(HOUSE_ONE, retained.file_key))[1] == PDF
    assert (await store.get(HOUSE_TWO, other_house.file_key))[1] == PNG


@pytest.mark.asyncio
async def test_custom_retention_requires_future_utc(tmp_path: Path) -> None:
    store = LocalFileStore(tmp_path, FakeClock())

    with pytest.raises(ValueError, match="UTC"):
        await store.put(
            HOUSE_ONE,
            FileKind.DOCUMENT,
            "application/pdf",
            PDF,
            retain_until=datetime(2026, 9, 26, tzinfo=UTC).replace(tzinfo=None),
        )
    with pytest.raises(ValueError, match="future"):
        await store.put(
            HOUSE_ONE,
            FileKind.DOCUMENT,
            "application/pdf",
            PDF,
            retain_until=FakeClock().now(),
        )


@pytest.mark.asyncio
async def test_concurrent_writes_have_distinct_keys(tmp_path: Path) -> None:
    store = LocalFileStore(tmp_path, FakeClock())

    stored = await asyncio.gather(
        *(store.put(HOUSE_ONE, FileKind.DOCUMENT, "application/pdf", PDF) for _ in range(5))
    )

    assert len({item.file_key for item in stored}) == 5
    for item in stored:
        assert (await store.get(HOUSE_ONE, item.file_key))[1] == PDF
