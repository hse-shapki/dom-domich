from pathlib import Path

import pytest

from dom_domych.config import AppSettings


def test_settings_require_secret_for_webhook_and_redact_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://secret@db/app")
    monkeypatch.setenv("MAX_INGRESS_MODE", "webhook")
    monkeypatch.delenv("MAX_WEBHOOK_SECRET", raising=False)
    with pytest.raises(ValueError):
        AppSettings.from_env()

    monkeypatch.setenv("MAX_WEBHOOK_SECRET", "webhook-secret")
    monkeypatch.setenv("MAX_BOT_TOKEN", "bot-secret")
    settings = AppSettings.from_env(require_max_token=True)

    assert settings.file_store_dir == Path("./var/files").resolve()
    assert "webhook-secret" not in repr(settings)
    assert "bot-secret" not in repr(settings)
    assert "postgresql+asyncpg" not in repr(settings)
