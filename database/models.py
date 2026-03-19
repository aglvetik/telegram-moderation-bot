from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from utils.formatters import from_iso


class ActionType(StrEnum):
    MUTE = "mute"
    UNMUTE = "unmute"
    KICK = "kick"
    BAN = "ban"
    UNBAN = "unban"
    SET_LEVEL = "set_level"
    REMOVE_LEVEL = "remove_level"


@dataclass(slots=True)
class ChatRecord:
    chat_id: int
    chat_type: str
    title: str | None
    owner_user_id: int | None
    bot_added_at: datetime
    is_active: bool
    settings_json: str | None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "ChatRecord":
        return cls(
            chat_id=row["chat_id"],
            chat_type=row["chat_type"],
            title=row["title"],
            owner_user_id=row["owner_user_id"],
            bot_added_at=from_iso(row["bot_added_at"]) or datetime.utcnow(),
            is_active=bool(row["is_active"]),
            settings_json=row["settings_json"],
        )


@dataclass(slots=True)
class UserCacheRecord:
    user_id: int
    username: str | None
    display_name: str
    first_name: str | None
    last_name: str | None
    first_seen_at: datetime
    last_seen_at: datetime
    updated_at: datetime
    last_seen_chat_id: int | None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "UserCacheRecord":
        fallback = datetime.utcnow()
        return cls(
            user_id=row["user_id"],
            username=row["username"],
            display_name=row["display_name"],
            first_name=row.get("first_name"),
            last_name=row.get("last_name"),
            first_seen_at=from_iso(row.get("first_seen_at")) or fallback,
            last_seen_at=from_iso(row.get("last_seen_at")) or fallback,
            updated_at=from_iso(row["updated_at"]) or fallback,
            last_seen_chat_id=row["last_seen_chat_id"],
        )


@dataclass(slots=True)
class MessageRefRecord:
    chat_id: int
    message_id: int
    sender_user_id: int | None
    sender_username: str | None
    sender_display_name: str | None
    reply_to_message_id: int | None
    message_date: datetime

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "MessageRefRecord":
        return cls(
            chat_id=row["chat_id"],
            message_id=row["message_id"],
            sender_user_id=row["sender_user_id"],
            sender_username=row["sender_username"],
            sender_display_name=row["sender_display_name"],
            reply_to_message_id=row["reply_to_message_id"],
            message_date=from_iso(row["message_date"]) or datetime.utcnow(),
        )


@dataclass(slots=True)
class AdminLevelRecord:
    id: int
    chat_id: int
    user_id: int
    admin_level: int
    granted_by_user_id: int | None
    granted_at: datetime
    updated_at: datetime

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "AdminLevelRecord":
        return cls(
            id=row["id"],
            chat_id=row["chat_id"],
            user_id=row["user_id"],
            admin_level=row["admin_level"],
            granted_by_user_id=row["granted_by_user_id"],
            granted_at=from_iso(row["granted_at"]) or datetime.utcnow(),
            updated_at=from_iso(row["updated_at"]) or datetime.utcnow(),
        )


@dataclass(slots=True)
class PunishmentRecord:
    id: int
    chat_id: int
    target_user_id: int
    target_username: str | None
    target_display_name: str | None
    moderator_user_id: int | None
    moderator_username: str | None
    moderator_display_name: str | None
    action_type: str
    reason: str | None
    duration_seconds: int | None
    mute_until: datetime | None
    created_at: datetime
    is_active: bool
    extra_data_json: str | None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "PunishmentRecord":
        return cls(
            id=row["id"],
            chat_id=row["chat_id"],
            target_user_id=row["target_user_id"],
            target_username=row["target_username"],
            target_display_name=row["target_display_name"],
            moderator_user_id=row["moderator_user_id"],
            moderator_username=row["moderator_username"],
            moderator_display_name=row["moderator_display_name"],
            action_type=row["action_type"],
            reason=row["reason"],
            duration_seconds=row["duration_seconds"],
            mute_until=from_iso(row["mute_until"]),
            created_at=from_iso(row["created_at"]) or datetime.utcnow(),
            is_active=bool(row["is_active"]),
            extra_data_json=row["extra_data_json"],
        )


@dataclass(slots=True)
class ActiveMuteRecord:
    id: int
    chat_id: int
    user_id: int
    started_at: datetime
    ends_at: datetime | None
    reason: str | None
    moderator_user_id: int | None
    is_active: bool

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "ActiveMuteRecord":
        return cls(
            id=row["id"],
            chat_id=row["chat_id"],
            user_id=row["user_id"],
            started_at=from_iso(row["started_at"]) or datetime.utcnow(),
            ends_at=from_iso(row.get("ends_at")),
            reason=row["reason"],
            moderator_user_id=row["moderator_user_id"],
            is_active=bool(row["is_active"]),
        )


@dataclass(slots=True)
class BanRecord:
    id: int
    chat_id: int
    user_id: int
    banned_at: datetime
    ends_at: datetime | None
    reason: str | None
    moderator_user_id: int | None
    is_active: bool

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "BanRecord":
        return cls(
            id=row["id"],
            chat_id=row["chat_id"],
            user_id=row["user_id"],
            banned_at=from_iso(row["banned_at"]) or datetime.utcnow(),
            ends_at=from_iso(row.get("ends_at")),
            reason=row["reason"],
            moderator_user_id=row["moderator_user_id"],
            is_active=bool(row["is_active"]),
        )
