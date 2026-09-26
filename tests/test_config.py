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


def test_runtime_settings_require_valid_llm_and_redact_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://secret@db/app")
    monkeypatch.setenv("MAX_INGRESS_MODE", "polling")
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    with pytest.raises(ValueError, match="LLM_BASE_URL"):
        AppSettings.from_env(require_llm=True)

    monkeypatch.setenv("LLM_BASE_URL", "http://token@inference.internal:8080")
    monkeypatch.setenv("LLM_MODEL", "demo-model")
    monkeypatch.setenv("LLM_MAX_TOKENS", "700")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "45")
    monkeypatch.setenv("LLM_ATTEMPTS", "3")
    settings = AppSettings.from_env(require_llm=True)

    assert settings.llm_model == "demo-model"
    assert settings.llm_max_tokens == 700
    assert settings.llm_timeout_seconds == 45
    assert settings.llm_attempts == 3
    assert "token@inference" not in repr(settings)
