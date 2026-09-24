import hashlib
from dataclasses import replace
from io import BytesIO
from typing import cast
from uuid import UUID

import pytest
from pypdf import PdfReader
from pypdf.generic import DictionaryObject

from dom_domych.domain.documents.snapshot import DocumentFact, DocumentKind, NoticeEntry
from dom_domych.infrastructure.documents.renderer import PdfRenderer, render_document
from tests.domain.test_document_snapshot import snapshot


@pytest.mark.parametrize("kind", list(DocumentKind))
def test_four_templates_show_frozen_facts_and_demo_label(kind: DocumentKind) -> None:
    revisions = {
        DocumentKind.APPEAL: "appeal-v1",
        DocumentKind.RESIDENT_POSITION: "resident-position-v1",
        DocumentKind.NOTIFICATION_REGISTER: "notification-register-v1",
        DocumentKind.COMPLAINT_DRAFT: "complaint-draft-v1",
    }
    source = replace(snapshot(), kind=kind, template_revision=revisions[kind])

    rendered = render_document(source)
    reader = PdfReader(BytesIO(rendered.content))
    text = "\n".join(page.extract_text() for page in reader.pages)

    assert rendered.content.startswith(b"%PDF-")
    assert rendered.sha256 == hashlib.sha256(rendered.content).hexdigest()
    assert rendered.snapshot_sha256 == source.sha256
    assert "ТЕСТОВЫЕ ДАННЫЕ / ДЕМО" in text
    assert source.title in text
    assert str(source.case_id) in text
    assert source.template_revision in text
    assert "Установить велопарковку" in text
    assert "Подходящих жителей: 12" in text
    assert len(reader.pages) >= 1
    resources = cast(DictionaryObject, reader.pages[0]["/Resources"].get_object())
    fonts = cast(DictionaryObject, resources["/Font"].get_object())
    embedded_fonts = [
        font.get_object().get("/FontDescriptor").get_object()
        for font in fonts.values()
        if font.get_object().get("/FontDescriptor") is not None
    ]
    assert len([font for font in embedded_fonts if "/FontFile2" in font]) >= 2
    if kind is DocumentKind.RESIDENT_POSITION:
        assert "не протокол ОСС" in text
        assert str(source.notices[0].resident_id) not in text
    if kind is DocumentKind.NOTIFICATION_REGISTER:
        assert str(source.notices[0].resident_id) in text


def test_notification_register_spans_pages_and_repeats_header() -> None:
    source = snapshot()
    notices = tuple(
        NoticeEntry(
            resident_id=UUID(int=index + 1),
            status=source.notices[0].status,
            attempted_at=source.notices[0].attempted_at,
            delivery_operation_id=None,
        )
        for index in range(90)
    )
    source = replace(
        source,
        kind=DocumentKind.NOTIFICATION_REGISTER,
        template_revision="notification-register-v1",
        notices=notices,
    )

    rendered = render_document(source)
    reader = PdfReader(BytesIO(rendered.content))

    assert len(reader.pages) >= 3
    assert all("Житель (внутренний ID)" in page.extract_text() for page in reader.pages)
    assert str(notices[-1].resident_id) in reader.pages[-1].extract_text()


def test_long_address_and_fact_are_not_lost() -> None:
    source = replace(
        snapshot(),
        house_address="Москва, улица Очень Длинная, дом 25, подъезд 2, этаж 12, " * 4,
        facts=(
            DocumentFact(
                key="Описание",
                value="Не горит свет в коридоре. " * 80,
                source_ref="case:revision:3",
            ),
        ),
    )

    rendered = render_document(source)
    text = "\n".join(
        page.extract_text() for page in PdfReader(BytesIO(rendered.content)).pages
    )

    assert "Очень Длинная" in text
    assert " ".join(text.split()).count("Не горит свет в коридоре") == 80


def test_renderer_rejects_mismatched_template_revision() -> None:
    with pytest.raises(ValueError, match="template revision"):
        render_document(replace(snapshot(), template_revision="unknown-v9"))


@pytest.mark.asyncio
async def test_process_pool_renders_snapshot_without_main_loop_blocking() -> None:
    async with PdfRenderer(max_workers=1) as renderer:
        rendered = await renderer.render(snapshot())

    assert rendered.snapshot_sha256 == snapshot().sha256
    assert rendered.content.startswith(b"%PDF-")
