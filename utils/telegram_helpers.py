from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import TypeVar

from aiogram import Bot
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import ChatMember, ChatPermissions, Message, User

from config import RetryConfig
from utils.exceptions import TelegramActionError
from utils.formatters import build_display_name

T = TypeVar("T")


def build_user_display_name(user: User) -> str:
    return build_display_name(user.first_name, user.last_name)


def is_active_chat_member(member: ChatMember | None) -> bool:
    if member is None:
        return False
    return member.status not in {ChatMemberStatus.LEFT, ChatMemberStatus.KICKED}


def is_admin_member(member: ChatMember | None) -> bool:
    if member is None:
        return False
    return member.status in {ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR}


def is_owner_member(member: ChatMember | None) -> bool:
    if member is None:
        return False
    return member.status == ChatMemberStatus.CREATOR


def member_has_restrict_rights(member: ChatMember | None) -> bool:
    if member is None:
        return False
    if is_owner_member(member):
        return True
    return bool(getattr(member, "can_restrict_members", False))


def member_has_delete_rights(member: ChatMember | None) -> bool:
    if member is None:
        return False
    if is_owner_member(member):
        return True
    return bool(getattr(member, "can_delete_messages", False))


def build_restrictive_permissions() -> ChatPermissions:
    return ChatPermissions(
        can_send_messages=False,
        can_send_audios=False,
        can_send_documents=False,
        can_send_photos=False,
        can_send_videos=False,
        can_send_video_notes=False,
        can_send_voice_notes=False,
        can_send_polls=False,
        can_send_other_messages=False,
        can_add_web_page_previews=False,
        can_change_info=False,
        can_invite_users=False,
        can_pin_messages=False,
        can_manage_topics=False,
    )


def build_unrestricted_permissions() -> ChatPermissions:
    return ChatPermissions(
        can_send_messages=True,
        can_send_audios=True,
        can_send_documents=True,
        can_send_photos=True,
        can_send_videos=True,
        can_send_video_notes=True,
        can_send_voice_notes=True,
        can_send_polls=True,
        can_send_other_messages=True,
        can_add_web_page_previews=True,
        can_change_info=True,
        can_invite_users=True,
        can_pin_messages=True,
        can_manage_topics=True,
    )


async def call_with_retry(
    operation: Callable[[], Awaitable[T]],
    *,
    logger: logging.Logger,
    retry: RetryConfig,
    context: str,
) -> T:
    attempt = 0
    while True:
        try:
            return await operation()
        except TelegramRetryAfter as exc:
            attempt += 1
            if attempt > retry.retries:
                logger.warning("Telegram retry-after exhausted for %s", context)
                raise TelegramActionError("❌ Telegram временно ограничил выполнение команды. Попробуйте чуть позже.") from exc
            delay = max(float(exc.retry_after), retry.base_delay_seconds * (2 ** (attempt - 1)))
            logger.warning("Retry-after for %s: waiting %.2fs", context, delay)
            await asyncio.sleep(delay)
        except TelegramForbiddenError as exc:
            logger.warning("Telegram forbidden for %s: %s", context, exc)
            raise TelegramActionError("❌ У бота недостаточно прав для выполнения этой команды.") from exc
        except TelegramBadRequest as exc:
            logger.warning("Telegram bad request for %s: %s", context, exc)
            message = str(exc).lower()
            if "administrator" in message or "admin" in message:
                raise TelegramActionError("❌ Невозможно применить санкцию.\nПользователь является администратором.") from exc
            if "participant_id_invalid" in message or "user not found" in message:
                raise TelegramActionError(
                    "❌ Не удалось выполнить действие.\nВозможно, пользователь недоступен боту или отсутствует в чате."
                ) from exc
            raise TelegramActionError(
                "❌ Не удалось выполнить действие.\n"
                "Возможно, у бота недостаточно прав или пользователь имеет более высокий статус."
            ) from exc
        except TelegramAPIError as exc:
            logger.exception("Telegram API error for %s", context)
            raise TelegramActionError("❌ Telegram временно недоступен. Попробуйте чуть позже.") from exc


async def safe_get_chat_member(bot: Bot, chat_id: int, user_id: int) -> ChatMember | None:
    try:
        return await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
    except TelegramAPIError:
        return None


async def delete_message_later(
    bot: Bot,
    message: Message,
    *,
    delay_seconds: int,
    logger: logging.Logger,
) -> None:
    if delay_seconds <= 0:
        return
    await asyncio.sleep(delay_seconds)
    try:
        await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
    except TelegramAPIError:
        logger.debug("Could not delete message %s in chat %s", message.message_id, message.chat.id)


def timestamp_to_datetime(value: int | datetime | None) -> datetime | None:
    if isinstance(value, datetime) or value is None:
        return value
    return datetime.fromtimestamp(value, tz=timezone.utc)
