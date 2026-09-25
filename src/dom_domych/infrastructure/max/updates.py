"""MAX Update → внутреннее событие; поля сверены с официальной OpenAPI schema."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from dom_domych.contracts.events import (
    CallbackPayload,
    EventEnvelope,
    EventName,
    EventSource,
    HouseBotPayload,
    LifecyclePayload,
    MessagePayload,
)


class MaxDto(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)


class MaxUser(MaxDto):
    user_id: int


class MaxRecipient(MaxDto):
    chat_id: int | None = None
    user_id: int | None = None


class MaxMessageBody(MaxDto):
    mid: str
    text: str | None = None
    attachments: list[dict[str, object]] | None = None


class MaxMessage(MaxDto):
    sender: MaxUser
    recipient: MaxRecipient
    timestamp: int
    body: MaxMessageBody


class MaxCallback(MaxDto):
    callback_id: str
    payload: str = Field(min_length=1)
    user: MaxUser
    timestamp: int


class MaxMessageUpdate(MaxDto):
    update_type: Literal["message_created", "message_edited"]
    timestamp: int
    message: MaxMessage


class MaxCallbackUpdate(MaxDto):
    update_type: Literal["message_callback"]
    timestamp: int
    callback: MaxCallback
    message: MaxMessage | None = None


class MaxRemovedUpdate(MaxDto):
    update_type: Literal["message_removed"]
    timestamp: int
    message_id: str
    chat_id: int
    user_id: int


class MaxLifecycleUpdate(MaxDto):
    update_type: Literal["bot_started", "bot_stopped"]
    timestamp: int
    user: MaxUser
    chat_id: int | None = None


class MaxBotMembershipUpdate(MaxDto):
    update_type: Literal["bot_added", "bot_removed"]
    timestamp: int
    chat_id: int
    user: MaxUser
    is_channel: bool


class MaxBotPermissionsUpdate(MaxDto):
    update_type: Literal["bot_admin_permissions_changed"]
    timestamp: int
    chat_id: int
    user_id: int
    bot_id: int
    is_channel: bool
    is_admin: bool
    permissions: list[str] | None = None


class MaxUnknownUpdate(MaxDto):
    update_type: str
    timestamp: int


def _timestamp(milliseconds: int) -> datetime:
    seconds, remainder = divmod(milliseconds, 1000)
    return datetime.fromtimestamp(seconds, UTC) + timedelta(milliseconds=remainder)


def _chat_id(message: MaxMessage) -> str:
    if message.recipient.chat_id is not None:
        return str(message.recipient.chat_id)
    return f"dm:{message.sender.user_id}"


def normalize_update(
    raw: dict[str, object], received_at: datetime
) -> tuple[str, EventEnvelope | None]:
    """Возвращает dedupe key и событие; unknown type остаётся raw-only без вызова агента."""

    update_type = raw.get("update_type")
    event_id = uuid4()
    if update_type in ("message_created", "message_edited"):
        message_update = MaxMessageUpdate.model_validate(raw)
        name = (
            EventName.MESSAGE_RECEIVED
            if message_update.update_type == "message_created"
            else EventName.MESSAGE_EDITED
        )
        message = message_update.message
        source_key = f"{message_update.update_type}:{_chat_id(message)}:{message.body.mid}"
        if message_update.update_type == "message_edited":
            revision_hash = hashlib.sha256(
                json.dumps(raw, sort_keys=True, ensure_ascii=False).encode()
            ).hexdigest()[:12]
            source_key += f":{message_update.timestamp}:{revision_hash}"
        payload = MessagePayload(
            chat_id=_chat_id(message),
            message_id=message.body.mid,
            sender_user_id=str(message.sender.user_id),
            text=message.body.text,
            attachment_refs=tuple(
                str(item.get("type", "unknown")) for item in (message.body.attachments or [])
            ),
        )
        return source_key, EventEnvelope(
            event_id=event_id,
            source=EventSource.MAX,
            source_key=source_key,
            name=name,
            occurred_at=_timestamp(message_update.timestamp),
            received_at=received_at,
            correlation_id=event_id,
            actor_user_id=str(message.sender.user_id),
            message=payload,
        )
    if update_type == "message_callback":
        callback_update = MaxCallbackUpdate.model_validate(raw)
        source_key = f"message_callback:{callback_update.callback.callback_id}"
        return source_key, EventEnvelope(
            event_id=event_id,
            source=EventSource.MAX,
            source_key=source_key,
            name=EventName.CALLBACK_RECEIVED,
            occurred_at=_timestamp(callback_update.timestamp),
            received_at=received_at,
            correlation_id=event_id,
            actor_user_id=str(callback_update.callback.user.user_id),
            callback=CallbackPayload(
                callback_id=callback_update.callback.callback_id,
                sender_user_id=str(callback_update.callback.user.user_id),
                action_token=callback_update.callback.payload,
                chat_id=(
                    _chat_id(callback_update.message)
                    if callback_update.message is not None
                    else None
                ),
            ),
        )
    if update_type == "message_removed":
        removed_update = MaxRemovedUpdate.model_validate(raw)
        source_key = f"message_removed:{removed_update.chat_id}:{removed_update.message_id}"
        return source_key, EventEnvelope(
            event_id=event_id,
            source=EventSource.MAX,
            source_key=source_key,
            name=EventName.MESSAGE_REMOVED,
            occurred_at=_timestamp(removed_update.timestamp),
            received_at=received_at,
            correlation_id=event_id,
            actor_user_id=str(removed_update.user_id),
            message=MessagePayload(
                chat_id=str(removed_update.chat_id),
                message_id=removed_update.message_id,
                sender_user_id=str(removed_update.user_id),
            ),
        )
    if update_type in ("bot_started", "bot_stopped"):
        lifecycle_update = MaxLifecycleUpdate.model_validate(raw)
        source_key = (
            f"{lifecycle_update.update_type}:{lifecycle_update.user.user_id}:"
            f"{lifecycle_update.timestamp}"
        )
        return source_key, EventEnvelope(
            event_id=event_id,
            source=EventSource.MAX,
            source_key=source_key,
            name=EventName.BOT_STARTED
            if lifecycle_update.update_type == "bot_started"
            else EventName.BOT_STOPPED,
            occurred_at=_timestamp(lifecycle_update.timestamp),
            received_at=received_at,
            correlation_id=event_id,
            actor_user_id=str(lifecycle_update.user.user_id),
            lifecycle=LifecyclePayload(
                user_id=str(lifecycle_update.user.user_id),
                chat_id=(
                    str(lifecycle_update.chat_id) if lifecycle_update.chat_id is not None else None
                ),
            ),
        )
    if update_type in ("bot_added", "bot_removed"):
        membership_update = MaxBotMembershipUpdate.model_validate(raw)
        source_key = (
            f"{membership_update.update_type}:{membership_update.chat_id}:"
            f"{membership_update.timestamp}"
        )
        return source_key, EventEnvelope(
            event_id=event_id,
            source=EventSource.MAX,
            source_key=source_key,
            name=EventName.HOUSE_BOT_MEMBERSHIP_CHANGED,
            occurred_at=_timestamp(membership_update.timestamp),
            received_at=received_at,
            correlation_id=event_id,
            actor_user_id=str(membership_update.user.user_id),
            house_bot=HouseBotPayload(
                chat_id=str(membership_update.chat_id),
                changed_by_user_id=str(membership_update.user.user_id),
                is_channel=membership_update.is_channel,
                change="added" if update_type == "bot_added" else "removed",
            ),
        )
    if update_type == "bot_admin_permissions_changed":
        permissions_update = MaxBotPermissionsUpdate.model_validate(raw)
        source_key = (
            f"bot_admin_permissions_changed:{permissions_update.chat_id}:"
            f"{permissions_update.bot_id}:{permissions_update.timestamp}"
        )
        return source_key, EventEnvelope(
            event_id=event_id,
            source=EventSource.MAX,
            source_key=source_key,
            name=EventName.HOUSE_BOT_PERMISSIONS_CHANGED,
            occurred_at=_timestamp(permissions_update.timestamp),
            received_at=received_at,
            correlation_id=event_id,
            actor_user_id=str(permissions_update.user_id),
            house_bot=HouseBotPayload(
                chat_id=str(permissions_update.chat_id),
                changed_by_user_id=str(permissions_update.user_id),
                is_channel=permissions_update.is_channel,
                change="permissions",
                bot_id=str(permissions_update.bot_id),
                is_admin=permissions_update.is_admin,
                permissions=(
                    tuple(permissions_update.permissions)
                    if permissions_update.permissions is not None
                    else None
                ),
            ),
        )
    MaxUnknownUpdate.model_validate(raw)
    digest = hashlib.sha256(
        json.dumps(raw, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    return f"unknown:{digest}", None
