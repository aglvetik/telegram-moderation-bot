from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import timedelta

from aiogram import Bot
from aiogram.enums import ChatMemberStatus

from config import AppConfig
from database.db import Database
from database.models import ActionType, ActiveMuteRecord
from database.repositories.bans_repo import BansRepository
from database.repositories.mutes_repo import MutesRepository
from database.repositories.punishments_repo import PunishmentsRepository
from database.repositories.users_repo import UsersRepository
from services.message_service import MessageService
from services.user_resolution_service import ResolvedUser
from utils.constants import DEFAULT_MUTE_DURATION_SECONDS, MessageCategory
from utils.exceptions import DatabaseOperationError
from utils.formatters import to_iso, utc_now
from utils.telegram_helpers import (
    build_restrictive_permissions,
    build_unrestricted_permissions,
    call_with_retry,
    is_active_chat_member,
    safe_get_chat_member,
)
from utils.validators import ensure_reason_length


@dataclass(slots=True)
class ActionResult:
    message: str
    category: MessageCategory = MessageCategory.MODERATION_RESULT
    delete_command: bool = True


class ModerationService:
    def __init__(
        self,
        *,
        config: AppConfig,
        database: Database,
        mutes_repo: MutesRepository,
        bans_repo: BansRepository,
        punishments_repo: PunishmentsRepository,
        users_repo: UsersRepository,
        message_service: MessageService,
    ) -> None:
        self.config = config
        self.database = database
        self.mutes_repo = mutes_repo
        self.bans_repo = bans_repo
        self.punishments_repo = punishments_repo
        self.users_repo = users_repo
        self.message_service = message_service
        self.logger = logging.getLogger(__name__)

    async def mute(
        self,
        *,
        bot: Bot,
        chat_id: int,
        moderator: ResolvedUser,
        target: ResolvedUser,
        duration_seconds: int,
        reason: str | None,
    ) -> ActionResult:
        reason = ensure_reason_length(reason)
        duration_seconds = duration_seconds or DEFAULT_MUTE_DURATION_SECONDS
        now = utc_now()
        until = now + timedelta(seconds=duration_seconds)
        existing = await self.mutes_repo.get_active_mute(chat_id, target.user_id)
        if existing and existing.ends_at > now:
            remaining = int((existing.ends_at - now).total_seconds())
            return ActionResult(
                message=self.message_service.mute_already_active(target, remaining),
                category=MessageCategory.TRANSIENT_SERVICE,
                delete_command=False,
            )

        await call_with_retry(
            lambda: bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=target.user_id,
                permissions=build_restrictive_permissions(),
                until_date=until,
            ),
            logger=self.logger,
            retry=self.config.retry,
            context=f"mute:{chat_id}:{target.user_id}",
        )

        try:
            async with self.database.transaction() as connection:
                await self.users_repo.upsert_user(
                    user_id=target.user_id,
                    username=target.username,
                    display_name=target.display_name,
                    first_name=None,
                    last_name=None,
                    last_seen_chat_id=chat_id,
                    connection=connection,
                )
                await self.punishments_repo.deactivate_entries(
                    chat_id=chat_id,
                    target_user_id=target.user_id,
                    action_types=(ActionType.MUTE.value,),
                    connection=connection,
                )
                await self.mutes_repo.complete_mute(chat_id=chat_id, user_id=target.user_id, connection=connection)
                await self.mutes_repo.create_active_mute(
                    chat_id=chat_id,
                    user_id=target.user_id,
                    started_at=now,
                    ends_at=until,
                    reason=reason,
                    moderator_user_id=moderator.user_id,
                    connection=connection,
                )
                await self.punishments_repo.add_entry(
                    chat_id=chat_id,
                    target_user_id=target.user_id,
                    target_username=target.username,
                    target_display_name=target.display_name,
                    moderator_user_id=moderator.user_id,
                    moderator_username=moderator.username,
                    moderator_display_name=moderator.display_name,
                    action_type=ActionType.MUTE.value,
                    reason=reason,
                    duration_seconds=duration_seconds,
                    mute_until=to_iso(until),
                    is_active=True,
                    extra_data_json=None,
                    connection=connection,
                )
        except sqlite3.IntegrityError:
            existing = await self.mutes_repo.get_active_mute(chat_id, target.user_id)
            if existing:
                remaining = int((existing.ends_at - utc_now()).total_seconds())
                return ActionResult(
                    message=self.message_service.mute_already_active(target, remaining),
                    category=MessageCategory.TRANSIENT_SERVICE,
                    delete_command=False,
                )
            raise
        except Exception as exc:
            await self._compensate_unmute(bot=bot, chat_id=chat_id, user_id=target.user_id)
            raise DatabaseOperationError("❌ Не удалось сохранить действие в базе данных. Ограничение было отменено.") from exc

        return ActionResult(message=self.message_service.mute_success(target, moderator, duration_seconds, reason))

    async def unmute(self, *, bot: Bot, chat_id: int, moderator: ResolvedUser, target: ResolvedUser) -> ActionResult:
        existing = await self.mutes_repo.get_active_mute(chat_id, target.user_id)

        await call_with_retry(
            lambda: bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=target.user_id,
                permissions=build_unrestricted_permissions(),
            ),
            logger=self.logger,
            retry=self.config.retry,
            context=f"unmute:{chat_id}:{target.user_id}",
        )

        try:
            async with self.database.transaction() as connection:
                await self.users_repo.upsert_user(
                    user_id=target.user_id,
                    username=target.username,
                    display_name=target.display_name,
                    first_name=None,
                    last_name=None,
                    last_seen_chat_id=chat_id,
                    connection=connection,
                )
                await self.mutes_repo.complete_mute(chat_id=chat_id, user_id=target.user_id, connection=connection)
                await self.punishments_repo.deactivate_entries(
                    chat_id=chat_id,
                    target_user_id=target.user_id,
                    action_types=(ActionType.MUTE.value,),
                    connection=connection,
                )
                await self.punishments_repo.add_entry(
                    chat_id=chat_id,
                    target_user_id=target.user_id,
                    target_username=target.username,
                    target_display_name=target.display_name,
                    moderator_user_id=moderator.user_id,
                    moderator_username=moderator.username,
                    moderator_display_name=moderator.display_name,
                    action_type=ActionType.UNMUTE.value,
                    reason=existing.reason if existing else "Снят вручную",
                    duration_seconds=None,
                    mute_until=None,
                    is_active=False,
                    extra_data_json=None,
                    connection=connection,
                )
        except Exception as exc:
            if existing and existing.ends_at > utc_now():
                await self._compensate_remute(bot=bot, chat_id=chat_id, user_id=target.user_id, ends_at=existing.ends_at)
            raise DatabaseOperationError("❌ Не удалось обновить базу данных после снятия мута.") from exc

        return ActionResult(message=self.message_service.unmute_success(target))

    async def kick(
        self,
        *,
        bot: Bot,
        chat_id: int,
        moderator: ResolvedUser,
        target: ResolvedUser,
        reason: str | None,
    ) -> ActionResult:
        reason = ensure_reason_length(reason)
        await call_with_retry(
            lambda: bot.ban_chat_member(chat_id=chat_id, user_id=target.user_id),
            logger=self.logger,
            retry=self.config.retry,
            context=f"kick-ban:{chat_id}:{target.user_id}",
        )
        await call_with_retry(
            lambda: bot.unban_chat_member(chat_id=chat_id, user_id=target.user_id, only_if_banned=True),
            logger=self.logger,
            retry=self.config.retry,
            context=f"kick-unban:{chat_id}:{target.user_id}",
        )
        try:
            async with self.database.transaction() as connection:
                await self.users_repo.upsert_user(
                    user_id=target.user_id,
                    username=target.username,
                    display_name=target.display_name,
                    first_name=None,
                    last_name=None,
                    last_seen_chat_id=chat_id,
                    connection=connection,
                )
                await self.punishments_repo.add_entry(
                    chat_id=chat_id,
                    target_user_id=target.user_id,
                    target_username=target.username,
                    target_display_name=target.display_name,
                    moderator_user_id=moderator.user_id,
                    moderator_username=moderator.username,
                    moderator_display_name=moderator.display_name,
                    action_type=ActionType.KICK.value,
                    reason=reason,
                    duration_seconds=None,
                    mute_until=None,
                    is_active=False,
                    extra_data_json=None,
                    connection=connection,
                )
        except Exception as exc:
            raise DatabaseOperationError("❌ Пользователь был удалён из чата, но запись в историю не сохранилась.") from exc
        return ActionResult(message=self.message_service.kick_success(target, moderator))

    async def ban(
        self,
        *,
        bot: Bot,
        chat_id: int,
        moderator: ResolvedUser,
        target: ResolvedUser,
        reason: str | None,
    ) -> ActionResult:
        reason = ensure_reason_length(reason)
        existing = await self.bans_repo.get_active_ban(chat_id, target.user_id)
        if existing:
            return ActionResult(
                message=self.message_service.already_banned(),
                category=MessageCategory.TRANSIENT_SERVICE,
                delete_command=False,
            )

        await call_with_retry(
            lambda: bot.ban_chat_member(chat_id=chat_id, user_id=target.user_id),
            logger=self.logger,
            retry=self.config.retry,
            context=f"ban:{chat_id}:{target.user_id}",
        )
        try:
            async with self.database.transaction() as connection:
                await self.users_repo.upsert_user(
                    user_id=target.user_id,
                    username=target.username,
                    display_name=target.display_name,
                    first_name=None,
                    last_name=None,
                    last_seen_chat_id=chat_id,
                    connection=connection,
                )
                await self.bans_repo.create_active_ban(
                    chat_id=chat_id,
                    user_id=target.user_id,
                    banned_at=utc_now(),
                    reason=reason,
                    moderator_user_id=moderator.user_id,
                    connection=connection,
                )
                await self.punishments_repo.deactivate_entries(
                    chat_id=chat_id,
                    target_user_id=target.user_id,
                    action_types=(ActionType.BAN.value,),
                    connection=connection,
                )
                await self.punishments_repo.add_entry(
                    chat_id=chat_id,
                    target_user_id=target.user_id,
                    target_username=target.username,
                    target_display_name=target.display_name,
                    moderator_user_id=moderator.user_id,
                    moderator_username=moderator.username,
                    moderator_display_name=moderator.display_name,
                    action_type=ActionType.BAN.value,
                    reason=reason,
                    duration_seconds=None,
                    mute_until=None,
                    is_active=True,
                    extra_data_json=None,
                    connection=connection,
                )
        except sqlite3.IntegrityError:
            return ActionResult(
                message=self.message_service.already_banned(),
                category=MessageCategory.TRANSIENT_SERVICE,
                delete_command=False,
            )
        except Exception as exc:
            await self._compensate_unban(bot=bot, chat_id=chat_id, user_id=target.user_id)
            raise DatabaseOperationError("❌ Не удалось сохранить бан в базе данных. Бан был отменён.") from exc

        return ActionResult(message=self.message_service.ban_success(target, moderator))

    async def unban(self, *, bot: Bot, chat_id: int, moderator: ResolvedUser, target: ResolvedUser) -> ActionResult:
        existing = await self.bans_repo.get_active_ban(chat_id, target.user_id)
        await call_with_retry(
            lambda: bot.unban_chat_member(chat_id=chat_id, user_id=target.user_id, only_if_banned=True),
            logger=self.logger,
            retry=self.config.retry,
            context=f"unban:{chat_id}:{target.user_id}",
        )
        try:
            async with self.database.transaction() as connection:
                await self.users_repo.upsert_user(
                    user_id=target.user_id,
                    username=target.username,
                    display_name=target.display_name,
                    first_name=None,
                    last_name=None,
                    last_seen_chat_id=chat_id,
                    connection=connection,
                )
                await self.bans_repo.deactivate_ban(chat_id=chat_id, user_id=target.user_id, connection=connection)
                await self.punishments_repo.deactivate_entries(
                    chat_id=chat_id,
                    target_user_id=target.user_id,
                    action_types=(ActionType.BAN.value,),
                    connection=connection,
                )
                await self.punishments_repo.add_entry(
                    chat_id=chat_id,
                    target_user_id=target.user_id,
                    target_username=target.username,
                    target_display_name=target.display_name,
                    moderator_user_id=moderator.user_id,
                    moderator_username=moderator.username,
                    moderator_display_name=moderator.display_name,
                    action_type=ActionType.UNBAN.value,
                    reason=existing.reason if existing else "Разбанен",
                    duration_seconds=None,
                    mute_until=None,
                    is_active=False,
                    extra_data_json=None,
                    connection=connection,
                )
        except Exception as exc:
            if existing:
                await self._compensate_reban(bot=bot, chat_id=chat_id, user_id=target.user_id)
            raise DatabaseOperationError("❌ Не удалось обновить базу данных после разбана.") from exc
        return ActionResult(message=self.message_service.unban_success(target))

    async def get_user_info_message(self, *, chat_id: int, target: ResolvedUser) -> str:
        level = await self._get_level(chat_id, target.user_id)
        active_mute = await self.mutes_repo.get_active_mute(chat_id, target.user_id)
        active_ban = await self.bans_repo.get_active_ban(chat_id, target.user_id)
        return self.message_service.user_info(target, level=level, active_mute=active_mute, active_ban=active_ban is not None)

    async def get_history_message(self, *, chat_id: int, target: ResolvedUser, limit: int) -> str:
        records = await self.punishments_repo.list_user_history(chat_id=chat_id, target_user_id=target.user_id, limit=limit)
        return self.message_service.history(target, records)

    async def get_active_mutes_message(self, *, chat_id: int, limit: int) -> str:
        mutes = await self.mutes_repo.list_active_mutes(chat_id=chat_id, limit=limit)
        identities: list[tuple[ResolvedUser, ActiveMuteRecord]] = []
        for mute in mutes:
            cached = await self.users_repo.get_by_user_id(mute.user_id)
            identities.append(
                (
                    ResolvedUser(
                        user_id=mute.user_id,
                        username=cached.username if cached else None,
                        display_name=cached.display_name if cached else f"ID {mute.user_id}",
                        source="cache",
                    ),
                    mute,
                )
            )
        return self.message_service.active_mutes(identities)

    async def expire_mute(self, *, bot: Bot, mute: ActiveMuteRecord) -> None:
        member = await safe_get_chat_member(bot, mute.chat_id, mute.user_id)
        if member is not None and is_active_chat_member(member):
            await call_with_retry(
                lambda: bot.restrict_chat_member(
                    chat_id=mute.chat_id,
                    user_id=mute.user_id,
                    permissions=build_unrestricted_permissions(),
                ),
                logger=self.logger,
                retry=self.config.retry,
                context=f"expire-mute:{mute.chat_id}:{mute.user_id}",
            )
        async with self.database.transaction() as connection:
            await self.mutes_repo.complete_mute(chat_id=mute.chat_id, user_id=mute.user_id, connection=connection)
            await self.punishments_repo.deactivate_entries(
                chat_id=mute.chat_id,
                target_user_id=mute.user_id,
                action_types=(ActionType.MUTE.value,),
                connection=connection,
            )

    async def verify_active_mute(self, *, bot: Bot, mute: ActiveMuteRecord) -> None:
        if mute.ends_at <= utc_now():
            await self.expire_mute(bot=bot, mute=mute)
            return

        member = await safe_get_chat_member(bot, mute.chat_id, mute.user_id)
        if member is None or not is_active_chat_member(member):
            return
        if member.status in {ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR}:
            return
        if member.status == ChatMemberStatus.RESTRICTED:
            return

        await call_with_retry(
            lambda: bot.restrict_chat_member(
                chat_id=mute.chat_id,
                user_id=mute.user_id,
                permissions=build_restrictive_permissions(),
                until_date=mute.ends_at,
            ),
            logger=self.logger,
            retry=self.config.retry,
            context=f"verify-mute:{mute.chat_id}:{mute.user_id}",
        )

    async def _compensate_unmute(self, *, bot: Bot, chat_id: int, user_id: int) -> None:
        try:
            await call_with_retry(
                lambda: bot.restrict_chat_member(chat_id=chat_id, user_id=user_id, permissions=build_unrestricted_permissions()),
                logger=self.logger,
                retry=self.config.retry,
                context=f"compensate-unmute:{chat_id}:{user_id}",
            )
        except Exception:
            self.logger.exception("Failed to compensate mute rollback for user %s in chat %s", user_id, chat_id)

    async def _compensate_remute(self, *, bot: Bot, chat_id: int, user_id: int, ends_at) -> None:
        try:
            await call_with_retry(
                lambda: bot.restrict_chat_member(
                    chat_id=chat_id,
                    user_id=user_id,
                    permissions=build_restrictive_permissions(),
                    until_date=ends_at,
                ),
                logger=self.logger,
                retry=self.config.retry,
                context=f"compensate-remute:{chat_id}:{user_id}",
            )
        except Exception:
            self.logger.exception("Failed to compensate unmute rollback for user %s in chat %s", user_id, chat_id)

    async def _compensate_unban(self, *, bot: Bot, chat_id: int, user_id: int) -> None:
        try:
            await call_with_retry(
                lambda: bot.unban_chat_member(chat_id=chat_id, user_id=user_id, only_if_banned=True),
                logger=self.logger,
                retry=self.config.retry,
                context=f"compensate-unban:{chat_id}:{user_id}",
            )
        except Exception:
            self.logger.exception("Failed to compensate ban rollback for user %s in chat %s", user_id, chat_id)

    async def _compensate_reban(self, *, bot: Bot, chat_id: int, user_id: int) -> None:
        try:
            await call_with_retry(
                lambda: bot.ban_chat_member(chat_id=chat_id, user_id=user_id),
                logger=self.logger,
                retry=self.config.retry,
                context=f"compensate-reban:{chat_id}:{user_id}",
            )
        except Exception:
            self.logger.exception("Failed to compensate unban rollback for user %s in chat %s", user_id, chat_id)

    async def _get_level(self, chat_id: int, user_id: int) -> int:
        row = await self.database.fetchone(
            "SELECT admin_level FROM admin_levels WHERE chat_id = ? AND user_id = ?;",
            (chat_id, user_id),
        )
        return int(row["admin_level"]) if row else 0
