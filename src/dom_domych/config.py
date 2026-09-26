"""Конфигурация процессов из окружения без чтения secret-файлов приложением."""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast
from urllib.parse import urlparse


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"{name} is required")
    return value


@dataclass(frozen=True, slots=True)
class AppSettings:
    database_url: str
    max_webhook_secret: str
    max_bot_token: str | None
    max_ingress_mode: Literal["webhook", "polling"]
    file_store_dir: Path
    worker_id: str
    payload_retention_days: int
    llm_base_url: str | None
    llm_model: str | None
    llm_max_tokens: int
    llm_timeout_seconds: float
    llm_attempts: int

    @classmethod
    def from_env(
        cls, *, require_max_token: bool = False, require_llm: bool = False
    ) -> "AppSettings":
        mode = os.environ.get("MAX_INGRESS_MODE", "webhook")
        if mode not in {"webhook", "polling"}:
            raise ValueError("MAX_INGRESS_MODE must be webhook or polling")
        token = os.environ.get("MAX_BOT_TOKEN", "").strip() or None
        if require_max_token and token is None:
            raise ValueError("MAX_BOT_TOKEN is required")
        webhook_secret = os.environ.get("MAX_WEBHOOK_SECRET", "").strip()
        if mode == "webhook" and not webhook_secret:
            raise ValueError("MAX_WEBHOOK_SECRET is required in webhook mode")
        retention_days = int(os.environ.get("PAYLOAD_RETENTION_DAYS", "30"))
        if not 1 <= retention_days <= 365:
            raise ValueError("PAYLOAD_RETENTION_DAYS must be between 1 and 365")
        llm_base_url = os.environ.get("LLM_BASE_URL", "").strip() or None
        llm_model = os.environ.get("LLM_MODEL", "").strip() or None
        if require_llm and (llm_base_url is None or llm_model is None):
            raise ValueError("LLM_BASE_URL and LLM_MODEL are required")
        if llm_base_url is not None:
            parsed = urlparse(llm_base_url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise ValueError("LLM_BASE_URL must be an absolute HTTP(S) URL")
        llm_max_tokens = int(os.environ.get("LLM_MAX_TOKENS", "512"))
        llm_timeout_seconds = float(os.environ.get("LLM_TIMEOUT_SECONDS", "30"))
        llm_attempts = int(os.environ.get("LLM_ATTEMPTS", "2"))
        if not 1 <= llm_max_tokens <= 8192:
            raise ValueError("LLM_MAX_TOKENS must be between 1 and 8192")
        if not 0 < llm_timeout_seconds <= 300:
            raise ValueError("LLM_TIMEOUT_SECONDS must be between 0 and 300")
        if not 1 <= llm_attempts <= 3:
            raise ValueError("LLM_ATTEMPTS must be between 1 and 3")
        return cls(
            database_url=_required("DATABASE_URL"),
            max_webhook_secret=webhook_secret,
            max_bot_token=token,
            max_ingress_mode=cast(Literal["webhook", "polling"], mode),
            file_store_dir=Path(os.environ.get("FILE_STORE_DIR", "./var/files")).resolve(),
            worker_id=os.environ.get("WORKER_ID", "dom-domych-worker"),
            payload_retention_days=retention_days,
            llm_base_url=llm_base_url,
            llm_model=llm_model,
            llm_max_tokens=llm_max_tokens,
            llm_timeout_seconds=llm_timeout_seconds,
            llm_attempts=llm_attempts,
        )

    def __repr__(self) -> str:
        return (
            "AppSettings(database_url='<redacted>', max_webhook_secret='<redacted>', "
            f"max_bot_token={'<redacted>' if self.max_bot_token else None!r}, "
            f"max_ingress_mode={self.max_ingress_mode!r}, "
            f"file_store_dir={str(self.file_store_dir)!r}, worker_id={self.worker_id!r}, "
            f"payload_retention_days={self.payload_retention_days}, "
            f"llm_base_url={'<redacted>' if self.llm_base_url else None!r}, "
            f"llm_model={self.llm_model!r}, llm_max_tokens={self.llm_max_tokens}, "
            f"llm_timeout_seconds={self.llm_timeout_seconds}, llm_attempts={self.llm_attempts})"
        )
