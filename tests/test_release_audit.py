from pathlib import Path

import pytest

from scripts.release_audit import create_release_evidence, scan_text_for_secrets


def test_secret_audit_accepts_placeholders_and_flags_real_values() -> None:
    assert not scan_text_for_secrets(
        "MAX_BOT_TOKEN=\nPOSTGRES_PASSWORD=change-me\nMAX_WEBHOOK_SECRET: ${MAX_WEBHOOK_SECRET}",
        "example",
    )
    findings = scan_text_for_secrets(
        "MAX_BOT_" + "TOKEN=real-production-token\n"
        "MAX_WEBHOOK_" + "SECRET: production-webhook-secret\n"
        "DATABASE_URL=postgresql+asyncpg://user:" + "actual-password@db/app",
        "unsafe",
    )
    assert {finding.pattern for finding in findings} == {
        "non_placeholder_max_bot_token",
        "non_placeholder_max_webhook_secret",
        "database_password_in_url",
    }


def test_release_evidence_rejects_malformed_image_digest(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="image must be"):
        create_release_evidence(tmp_path / "evidence", ["app=sha256:not-a-digest"])
