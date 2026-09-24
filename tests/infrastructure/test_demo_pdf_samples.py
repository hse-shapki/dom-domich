from dom_domych.domain.documents.snapshot import DocumentKind, DocumentMode
from scripts.generate_zamira_demo_pdfs import sample_snapshots


def test_demo_pdf_samples_cover_four_kinds_with_synthetic_facts() -> None:
    snapshots = sample_snapshots()

    assert {item.kind for item in snapshots} == set(DocumentKind)
    assert all(item.mode is DocumentMode.DEMO for item in snapshots)
    assert all(
        item.tally is not None and item.tally.eligible == 12 for item in snapshots
    )
    register = next(
        item for item in snapshots if item.kind is DocumentKind.NOTIFICATION_REGISTER
    )
    assert len(register.notices) == 90
    assert len({item.resident_id for item in register.notices}) == 90
