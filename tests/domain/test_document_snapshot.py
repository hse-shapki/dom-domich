from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone

import pytest

from dom_domych.domain.documents.snapshot import (
    DocumentFact,
    DocumentKind,
    DocumentMode,
    DocumentSnapshot,
    NoticeEntry,
    NoticeStatus,
)
from dom_domych.domain.polls.policy import VoteTally
from tests.fixtures.zamira_house import HOUSE_ONE, synthetic_id


def snapshot() -> DocumentSnapshot:
    return DocumentSnapshot(
        kind=DocumentKind.RESIDENT_POSITION,
        mode=DocumentMode.DEMO,
        template_revision="resident-position-v1",
        house_id=HOUSE_ONE,
        case_id=synthetic_id("document-case"),
        case_revision=3,
        audience_id=synthetic_id("document-audience"),
        audience_revision=2,
        poll_id=synthetic_id("document-poll"),
        poll_revision=4,
        request_id=None,
        request_revision=None,
        title="Позиция жителей по велопарковке",
        house_address="Тестовый дом, подъезд 2",
        facts=(
            DocumentFact(
                key="proposal",
                value="Установить велопарковку",
                source_ref="case:revision:3",
            ),
        ),
        tally=VoteTally(eligible=12, yes=5, no=2),
        notices=(
            NoticeEntry(
                resident_id=synthetic_id("resident-1"),
                status=NoticeStatus.SENT,
                attempted_at=datetime(2026, 9, 25, 12, tzinfo=timezone.utc),
                delivery_operation_id=synthetic_id("delivery-1"),
            ),
        ),
        created_at=datetime(2026, 9, 25, 13, tzinfo=timezone.utc),
    )


def test_snapshot_hash_is_stable_and_changes_with_facts_or_revisions() -> None:
    first = snapshot()

    assert first.canonical_bytes() == snapshot().canonical_bytes()
    assert first.sha256 == snapshot().sha256
    assert (
        replace(first, tally=VoteTally(eligible=12, yes=6, no=2)).sha256 != first.sha256
    )
    assert replace(first, case_revision=4).sha256 != first.sha256
    assert (
        replace(first, template_revision="resident-position-v2").sha256 != first.sha256
    )


def test_snapshot_cannot_be_mutated_after_capture() -> None:
    first = snapshot()
    field_name = "title"

    with pytest.raises(FrozenInstanceError):
        setattr(first, field_name, "Подменённый итог")


def test_snapshot_rejects_missing_source_and_duplicate_notifications() -> None:
    with pytest.raises(ValueError, match="source"):
        DocumentFact(key="proposal", value="Установить", source_ref="")
    first = snapshot()

    with pytest.raises(ValueError, match="repeat"):
        replace(first, notices=first.notices + first.notices)


def test_snapshot_rejects_vote_count_without_poll_reference() -> None:
    first = snapshot()

    with pytest.raises(ValueError, match="poll reference"):
        replace(first, poll_id=None, poll_revision=None)


def test_snapshot_requires_utc_and_matching_revision_pairs() -> None:
    first = snapshot()

    with pytest.raises(ValueError, match="UTC"):
        replace(
            first,
            created_at=datetime(2026, 9, 25, 13, tzinfo=timezone.utc).replace(
                tzinfo=None
            ),
        )
    with pytest.raises(ValueError, match="set together"):
        replace(first, poll_revision=None)
