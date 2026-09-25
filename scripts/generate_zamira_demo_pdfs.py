"""Воспроизвести четыре синтетических образца PDF без MAX и персональных данных."""

import argparse
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from dom_domych.domain.documents.snapshot import (
    DocumentFact,
    DocumentKind,
    DocumentMode,
    DocumentSnapshot,
    NoticeEntry,
    NoticeStatus,
)
from dom_domych.domain.polls.policy import VoteTally
from dom_domych.infrastructure.documents.renderer import render_document


def synthetic_id(name: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"dom-domich-demo:{name}")


def sample_snapshots() -> tuple[DocumentSnapshot, ...]:
    """Фиксированные факты позволяют сверить текст и snapshot hash после генерации."""

    created_at = datetime(2026, 9, 25, 13, tzinfo=UTC)
    first = DocumentSnapshot(
        kind=DocumentKind.RESIDENT_POSITION,
        mode=DocumentMode.DEMO,
        template_revision="resident-position-v1",
        house_id=synthetic_id("house-one"),
        case_id=synthetic_id("document-case"),
        case_revision=3,
        audience_id=synthetic_id("document-audience"),
        audience_revision=2,
        poll_id=synthetic_id("document-poll"),
        poll_revision=4,
        policy_revision="demo-initiative-v1",
        request_id=None,
        request_revision=None,
        title="Позиция жителей по велопарковке",
        house_address=(
            "Москва, улица Очень Длинная, дом 25, корпус 2, подъезд 2, этаж 5, стояк холодной воды"
        ),
        facts=(DocumentFact("proposal", "Установить велопарковку", "case:revision:3"),),
        tally=VoteTally(eligible=12, yes=5, no=2),
        notices=(
            NoticeEntry(
                resident_id=synthetic_id("resident-1"),
                status=NoticeStatus.SENT,
                attempted_at=datetime(2026, 9, 25, 12, tzinfo=UTC),
                delivery_operation_id=synthetic_id("delivery-1"),
            ),
        ),
        created_at=created_at,
    )
    result: list[DocumentSnapshot] = []
    for kind in DocumentKind:
        current = replace(
            first,
            kind=kind,
            template_revision=f"{kind.value.replace('_', '-')}-v1",
        )
        if kind is not DocumentKind.RESIDENT_POSITION:
            current = replace(
                current,
                title="Нет света на 5-м этаже",
                facts=(
                    DocumentFact(
                        "problem",
                        "На 5-м этаже подъезда 2 не горит освещение общего коридора.",
                        "case:revision:3",
                    ),
                    DocumentFact(
                        "location",
                        "Подъезд 2, этаж 5. По реестру затронуты 12 подтверждённых жителей.",
                        "audience:revision:2",
                    ),
                ),
            )
        if kind is DocumentKind.COMPLAINT_DRAFT:
            current = replace(
                current,
                facts=current.facts
                + (
                    DocumentFact(
                        "request_status",
                        "Тестовый исполнитель отметил выполнение, но жители сообщили, "
                        "что свет по-прежнему не горит.",
                        "request:revision:2",
                    ),
                ),
                request_id=UUID(int=500),
                request_revision=2,
            )
        if kind is DocumentKind.NOTIFICATION_REGISTER:
            current = replace(
                current,
                notices=tuple(
                    NoticeEntry(
                        UUID(int=index + 1),
                        NoticeStatus.SENT if index % 3 else NoticeStatus.DELIVERY_UNKNOWN,
                        created_at,
                        UUID(int=index + 1000),
                    )
                    for index in range(90)
                ),
            )
        result.append(current)
    return tuple(result)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    output_dir: Path = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    for snapshot in sample_snapshots():
        rendered = render_document(snapshot)
        path = output_dir / f"demo-{snapshot.kind.value}.pdf"
        path.write_bytes(rendered.content)
        print(f"{path}: snapshot={rendered.snapshot_sha256} pdf={rendered.sha256}")


if __name__ == "__main__":
    main()
