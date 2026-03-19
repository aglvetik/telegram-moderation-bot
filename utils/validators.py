from __future__ import annotations

import re

from aiogram.enums import ChatType

from utils.constants import (
    DEFAULT_REASON,
    MAX_ADMIN_LEVEL,
    MAX_ASSIGNABLE_ADMIN_LEVEL,
    MAX_REASON_LENGTH,
    MIN_ADMIN_LEVEL,
    ZERO_WIDTH_CHARACTERS,
)
from utils.exceptions import ParseCommandError, UnsupportedChatError, ValidationError

USERNAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{4,31}$")


def normalize_command_text(text: str) -> str:
    normalized = text.replace("\n", " ").replace("\r", " ")
    for char in ZERO_WIDTH_CHARACTERS:
        normalized = normalized.replace(char, "")
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def extract_command_keyword(text: str) -> str:
    normalized = normalize_command_text(text)
    if not normalized:
        return ""
    return normalized.split(" ", 1)[0].lower()


def normalize_username(username: str | None) -> str | None:
    if username is None:
        return None
    normalized = username.strip().lstrip("@").lower()
    return normalized or None


def looks_like_username_token(token: str) -> bool:
    return bool(USERNAME_PATTERN.fullmatch(token.strip().lstrip("@")))


def ensure_reason_length(reason: str | None) -> str:
    if not reason:
        return DEFAULT_REASON
    reason = reason.strip()
    if len(reason) > MAX_REASON_LENGTH:
        raise ValidationError(f"❌ Причина слишком длинная.\nМаксимум: {MAX_REASON_LENGTH} символов.")
    return reason


def validate_admin_level(level: int) -> int:
    if level < MIN_ADMIN_LEVEL or level > MAX_ADMIN_LEVEL:
        raise ValidationError("❌ Уровень модерации должен быть от 0 до 5.")
    return level


def validate_assignable_admin_level(level: int) -> int:
    if level < MIN_ADMIN_LEVEL or level > MAX_ASSIGNABLE_ADMIN_LEVEL:
        raise ValidationError(
            "❌ Через команды бота можно назначать уровни только от 0 до 4.\n"
            "Уровень 5 зарезервирован за владельцем системы."
        )
    return level


def ensure_group_chat(chat_type: str) -> None:
    if chat_type in {ChatType.PRIVATE, ChatType.CHANNEL}:
        raise UnsupportedChatError(
            "ℹ️ Команды модерации работают только в группах и супергруппах."
            if chat_type == ChatType.PRIVATE
            else "ℹ️ Команды модерации пользователей доступны только в группах и супергруппах."
        )


def ensure_text_present(text: str | None) -> str:
    if not text:
        raise ParseCommandError("❌ Не удалось распознать команду.")
    return text
