"""PDF-шаблоны из зафиксированного снимка, без обращения к БД или сети."""

import asyncio
import hashlib
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from html import escape
from io import BytesIO
from pathlib import Path
from typing import Self

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    BaseDocTemplate,
    Flowable,
    HRFlowable,
    KeepTogether,
    LongTable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    TableStyle,
)

from dom_domych.domain.documents.snapshot import (
    DocumentKind,
    DocumentSnapshot,
    NoticeStatus,
)

_FONT_DIR = Path(__file__).resolve().parents[2] / "assets" / "fonts"
_FONT_REGULAR = _FONT_DIR / "DejaVuSans.ttf"
_FONT_BOLD = _FONT_DIR / "DejaVuSans-Bold.ttf"
_FONT_NAME = "DomDejaVu"
_FONT_BOLD_NAME = "DomDejaVu-Bold"
_MAX_DOCUMENT_BYTES = 8_000_000

_TITLES = {
    DocumentKind.APPEAL: "Обращение по проблеме дома",
    DocumentKind.RESIDENT_POSITION: "Протокол позиции жителей",
    DocumentKind.NOTIFICATION_REGISTER: "Реестр уведомлений",
    DocumentKind.COMPLAINT_DRAFT: "Черновик жалобы",
}
_TEMPLATE_REVISIONS = {
    DocumentKind.APPEAL: "appeal-v1",
    DocumentKind.RESIDENT_POSITION: "resident-position-v1",
    DocumentKind.NOTIFICATION_REGISTER: "notification-register-v1",
    DocumentKind.COMPLAINT_DRAFT: "complaint-draft-v1",
}
_NOTICE_LABELS = {
    NoticeStatus.PENDING: "Ожидает отправки",
    NoticeStatus.SENT: "Отправлено",
    NoticeStatus.FAILED: "Ошибка отправки",
    NoticeStatus.DELIVERY_UNKNOWN: "Доставка не подтверждена",
}
_FACT_LABELS = {
    "proposal": "Предложение",
    "problem": "Проблема",
    "location": "Место",
    "evidence": "Подтверждение",
    "recipient": "Адресат",
    "request_status": "Статус обращения",
}


@dataclass(frozen=True, slots=True)
class RenderedDocument:
    content: bytes
    sha256: str
    snapshot_sha256: str
    template_revision: str
    mime_type: str = "application/pdf"


def _register_fonts() -> None:
    if _FONT_NAME not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(_FONT_NAME, str(_FONT_REGULAR)))
    if _FONT_BOLD_NAME not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(_FONT_BOLD_NAME, str(_FONT_BOLD)))


def _style(name: str, *, size: int, leading: int, bold: bool = False) -> ParagraphStyle:
    return ParagraphStyle(
        name=name,
        fontName=_FONT_BOLD_NAME if bold else _FONT_NAME,
        fontSize=size,
        leading=leading,
        textColor=colors.HexColor("#172A3A"),
        alignment=TA_LEFT,
        spaceAfter=5,
        splitLongWords=1,
        allowWidows=0,
        allowOrphans=0,
    )


def _paragraph(value: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(value).replace("\n", "<br/>"), style)


def _table(rows: list[list[Paragraph]], widths: list[int]) -> LongTable:
    table = LongTable(rows, colWidths=widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8F0F4")),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#C5D1D8")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return table


def _footer(canvas: Canvas, document: BaseDocTemplate) -> None:
    canvas.saveState()
    canvas.setFont(_FONT_NAME, 8)
    canvas.setFillColor(colors.HexColor("#657681"))
    canvas.drawString(42, 30, "Дом Домыч · подготовленный документ")
    canvas.drawRightString(A4[0] - 42, 30, f"Страница {document.page}")
    canvas.restoreState()


def render_document(snapshot: DocumentSnapshot) -> RenderedDocument:
    """Рендерит только frozen snapshot; источник истины не перечитывается во время PDF."""

    if snapshot.template_revision != _TEMPLATE_REVISIONS[snapshot.kind]:
        raise ValueError("unsupported template revision for document kind")
    _register_fonts()
    regular = _style("body", size=9, leading=14)
    small = _style("small", size=7, leading=11)
    heading = _style("heading", size=16, leading=21, bold=True)
    subheading = _style("subheading", size=11, leading=15, bold=True)
    label = _style("label", size=8, leading=12, bold=True)
    label.alignment = TA_CENTER

    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=42,
        rightMargin=42,
        topMargin=42,
        bottomMargin=55,
        title=_TITLES[snapshot.kind],
        author="Дом Домыч",
    )
    story: list[Flowable] = [
        _paragraph(_TITLES[snapshot.kind], heading),
        _paragraph(
            "ТЕСТОВЫЕ ДАННЫЕ / ДЕМО" if snapshot.mode.value == "demo" else "ЧЕРНОВИК",
            subheading,
        ),
        HRFlowable(width="100%", thickness=1, color=colors.HexColor("#53778B")),
        Spacer(1, 12),
        _paragraph(f"Тема: {snapshot.title}", subheading),
        _paragraph(f"Адрес: {snapshot.house_address}", regular),
        _paragraph(f"Дело: {snapshot.case_id} · редакция {snapshot.case_revision}", small),
        _paragraph(
            f"Аудитория: {snapshot.audience_id} · редакция {snapshot.audience_revision}",
            small,
        ),
        _paragraph(f"Снимок: {snapshot.sha256}", small),
        _paragraph(f"Шаблон: {snapshot.template_revision}", small),
        _paragraph(f"Сформировано: {snapshot.created_at:%d.%m.%Y %H:%M} UTC", small),
        Spacer(1, 9),
    ]
    if snapshot.policy_revision is not None:
        story.append(_paragraph(f"Правило подсчёта: {snapshot.policy_revision}", small))
    if snapshot.request_id is not None:
        story.append(
            _paragraph(
                f"Обращение: {snapshot.request_id} · редакция {snapshot.request_revision}",
                small,
            )
        )

    if snapshot.kind is DocumentKind.RESIDENT_POSITION:
        story.append(_paragraph("Это позиция жителей по опросу, не протокол ОСС.", regular))
    elif snapshot.kind is DocumentKind.APPEAL:
        story.append(
            _paragraph(
                "Обращение подготовлено для проверки и отправки уполномоченным лицом.",
                regular,
            )
        )
    elif snapshot.kind is DocumentKind.COMPLAINT_DRAFT:
        story.append(
            _paragraph(
                "Черновик жалобы: перед отправкой требуется проверка фактов и адресата.",
                regular,
            )
        )
    else:
        story.append(
            _paragraph(
                "Реестр фиксирует попытки уведомления, а не гарантирует доставку.",
                regular,
            )
        )

    if snapshot.facts:
        story.append(Spacer(1, 9))
        story.append(_paragraph("Зафиксированные сведения", subheading))
        for fact in snapshot.facts:
            story.append(
                KeepTogether(
                    [
                        _paragraph(_FACT_LABELS.get(fact.key, fact.key), subheading),
                        _paragraph(fact.value, regular),
                        _paragraph(f"Источник: {fact.source_ref}", small),
                        Spacer(1, 6),
                    ]
                )
            )

    if snapshot.tally is not None:
        tally = snapshot.tally
        story.append(Spacer(1, 9))
        story.append(_paragraph("Итог явных ответов", subheading))
        story.append(
            _paragraph(
                f"Подходящих жителей: {tally.eligible}. Ответили: {tally.answered}. "
                f"За: {tally.yes}. Против: {tally.no}. Не ответили: "
                f"{tally.eligible - tally.answered}.",
                regular,
            )
        )
        story.append(
            _paragraph(f"Опрос: {snapshot.poll_id} · редакция {snapshot.poll_revision}", small)
        )

    if snapshot.kind is DocumentKind.NOTIFICATION_REGISTER:
        story.append(Spacer(1, 9))
        story.append(_paragraph("Отправка уведомлений", subheading))
        rows = [
            [
                _paragraph("Житель (внутренний ID)", label),
                _paragraph("Статус", label),
                _paragraph("Попытка, UTC", label),
            ]
        ]
        for notice in snapshot.notices:
            rows.append(
                [
                    _paragraph(str(notice.resident_id), small),
                    _paragraph(_NOTICE_LABELS[notice.status], small),
                    _paragraph(
                        notice.attempted_at.strftime("%d.%m.%Y %H:%M")
                        if notice.attempted_at is not None
                        else "—",
                        small,
                    ),
                ]
            )
        if not snapshot.notices:
            rows.append(
                [
                    _paragraph("Нет записей", small),
                    _paragraph("—", small),
                    _paragraph("—", small),
                ]
            )
        story.append(_table(rows, [225, 175, 110]))
        story.append(Spacer(1, 8))
        story.append(
            _paragraph(
                "Документ содержит служебные идентификаторы. Доступ только уполномоченным.",
                small,
            )
        )

    story.append(Spacer(1, 14))
    story.append(
        _paragraph(
            "Подготовлено автоматически по зафиксированному снимку. "
            "Фактическая отправка и официальный статус подтверждаются отдельно.",
            small,
        )
    )
    document.build(story, onFirstPage=_footer, onLaterPages=_footer)
    content = buffer.getvalue()
    if len(content) > _MAX_DOCUMENT_BYTES:
        raise ValueError("rendered PDF exceeds size limit")
    return RenderedDocument(
        content=content,
        sha256=hashlib.sha256(content).hexdigest(),
        snapshot_sha256=snapshot.sha256,
        template_revision=snapshot.template_revision,
    )


class PdfRenderer:
    """Ограниченный process pool не блокирует asyncio loop синхронным ReportLab."""

    def __init__(self, max_workers: int = 2) -> None:
        if max_workers < 1 or max_workers > 4:
            raise ValueError("max_workers must be between 1 and 4")
        self._pool = ProcessPoolExecutor(max_workers=max_workers)

    async def render(self, snapshot: DocumentSnapshot) -> RenderedDocument:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._pool, render_document, snapshot)

    def close(self) -> None:
        self._pool.shutdown(wait=True, cancel_futures=True)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, _type: object, _value: object, _traceback: object) -> None:
        await asyncio.to_thread(self.close)
