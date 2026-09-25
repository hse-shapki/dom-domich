"""Конфигурация процессов из окружения без чтения secret-файлов приложением."""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast


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

    @classmethod
    def from_env(cls, *, require_max_token: bool = False) -> "AppSettings":
        mode = os.environ.get("MAX_INGRESS_MODE", "webhook")
        if mode not in {"webhook", "polling"}:
            raise ValueError("MAX_INGRESS_MODE must be webhook or polling")
        token = os.environ.get("MAX_BOT_TOKEN", "").strip() or None
        if require_max_token and token is None:
            raise ValueError("MAX_BOT_TOKEN is required")
        webhook_secret = os.environ.get("MAX_WEBHOOK_SECRET", "").strip()
        if mode == "webhook" and not webhook_secret:
            raise ValueError("MAX_WEBHOOK_SECRET is required in webhook mode")
        return cls(
            database_url=_required("DATABASE_URL"),
            max_webhook_secret=webhook_secret,
            max_bot_token=token,
            max_ingress_mode=cast(Literal["webhook", "polling"], mode),
            file_store_dir=Path(os.environ.get("FILE_STORE_DIR", "./var/files")).resolve(),
            worker_id=os.environ.get("WORKER_ID", "dom-domych-worker"),
        )

    def __repr__(self) -> str:
        return (
            "AppSettings(database_url='<redacted>', max_webhook_secret='<redacted>', "
            f"max_bot_token={'<redacted>' if self.max_bot_token else None!r}, "
            f"max_ingress_mode={self.max_ingress_mode!r}, "
            f"file_store_dir={str(self.file_store_dir)!r}, worker_id={self.worker_id!r})"
        )
