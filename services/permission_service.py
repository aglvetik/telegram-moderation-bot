from __future__ import annotations

from typing import TYPE_CHECKING

from aiogram import Bot
from aiogram.enums import ChatMemberStatus
from aiogram.types import User

from database.db import Database
from database.repositories.admin_levels_repo import AdminLevelsRepository
from database.repositories.chats_repo import ChatsRepository
from database.repositories.punishments_repo import PunishmentsRepository
from database.repositories.users_repo import UsersRepository
from services.message_service import MessageService
from services.user_resolution_service import ResolvedUser
from utils.constants import LEVEL_FOUR_ASSIGNMENT_CAP, MAX_ASSIGNABLE_ADMIN_LEVEL, MODERATION_REQUIRED_LEVELS
from utils.exceptions import PermissionDeniedError, TargetResolutionError, ValidationError
from utils.telegram_helpers import is_active_chat_member, is_admin_member, member_has_restrict_rights, safe_get_chat_member

if TYPE_CHECKING:
    from services.chat_service import ChatService


class PermissionService:
    """Centralizes internal authorization, hierarchy checks, and bot-rights validation."""

    def __init__(
        self,
        *,
        database: Database,
        admin_levels_repo: AdminLevelsRepository,
        chats_repo: ChatsRepository,
        punishments_repo: PunishmentsRepository,
        users_repo: UsersRepository,
        message_service: MessageService,
        system_owner_user_id: int | None,
        chat_service: ChatService | None = None,
    ) -> None:
        self.database = database
        self.admin_levels_repo = admin_levels_repo
        self.chats_repo = chats_repo
        self.punishments_repo = punishments_repo
        self.users_repo = users_repo
        self.message_service = message_service
        self.system_owner_user_id = system_owner_user_id
        self.chat_service = chat_service

    async def get_level(self, chat_id: int, user_id: int, *, bot: Bot | None = None, member=None) -> int:
        await self._maybe_refresh_owner_state(bot=bot, chat_id=chat_id, user_id=user_id, member=member)
        return await self._get_public_level(chat_id, user_id)

    async def get_my_level(self, chat_id: int, user: User, *, bot: Bot | None = None) -> int:
        await self._maybe_refresh_owner_state(bot=bot, chat_id=chat_id, user_id=user.id)
        return await self._get_public_level(chat_id, user.id)

    async def get_effective_level(self, chat_id: int, user_id: int, *, bot: Bot | None = None, member=None) -> int:
        await self._maybe_refresh_owner_state(bot=bot, chat_id=chat_id, user_id=user_id, member=member)
        return await self._get_effective_level(chat_id, user_id)

    async def get_my_effective_level(self, chat_id: int, user: User, *, bot: Bot | None = None) -> int:
        await self._maybe_refresh_owner_state(bot=bot, chat_id=chat_id, user_id=user.id)
        return await self._get_effective_level(chat_id, user.id)

    async def ensure_moderation_allowed(
        self,
        *,
        bot: Bot,
        chat_id: int,
        actor: User,
        target: ResolvedUser,
        action: str,
    ) -> tuple[int, int]:
        required_level = MODERATION_REQUIRED_LEVELS[action]
        caller_level, _ = await self._ensure_actor_ready(bot, chat_id, actor, required_level=required_level)
        await self._ensure_bot_can_do_action(bot, chat_id, action)
        await self._maybe_refresh_owner_state(bot=bot, chat_id=chat_id, user_id=target.user_id, member=target.member)
        # System-owner level 5 is an authorization override for the caller only.
        # It must not create moderation immunity when that user is the target.
        target_level = await self._get_public_level(chat_id, target.user_id)
        chat_record = await self.chats_repo.get_chat(chat_id)

        if target.user_id == actor.id:
            raise PermissionDeniedError(self.message_service.target_is_self())
        if target.user_id == bot.id:
            raise PermissionDeniedError(self.message_service.target_is_bot())
        if chat_record and chat_record.owner_user_id == target.user_id:
            raise PermissionDeniedError(self.message_service.target_is_owner())
        if target_level >= caller_level:
            raise PermissionDeniedError(self.message_service.target_same_or_higher_level())
        if target.member and is_admin_member(target.member):
            raise PermissionDeniedError(self.message_service.target_admin_protected())
        if action in {"mute", "unmute", "kick"} and target.member is None:
            raise TargetResolutionError(self.message_service.target_unavailable())
        return caller_level, target_level

    async def ensure_view_access(self, *, bot: Bot, chat_id: int, actor: User, required_level: int) -> int:
        caller_level, _ = await self._ensure_actor_ready(bot, chat_id, actor, required_level=required_level)
        return caller_level

    async def ensure_manage_levels_allowed(
        self,
        *,
        bot: Bot,
        chat_id: int,
        actor: User,
        target: ResolvedUser | None = None,
    ) -> tuple[int, int | None]:
        caller_level, _ = await self._ensure_actor_ready(
            bot,
            chat_id,
            actor,
            required_level=MODERATION_REQUIRED_LEVELS["manage_levels"],
        )
        target_level: int | None = None
        if target is not None:
            await self._maybe_refresh_owner_state(bot=bot, chat_id=chat_id, user_id=target.user_id, member=target.member)
            if target.user_id == actor.id:
                raise PermissionDeniedError(self.message_service.target_is_self())
            if target.user_id == bot.id:
                raise PermissionDeniedError(self.message_service.target_is_bot())
            chat_record = await self.chats_repo.get_chat(chat_id)
            if chat_record and chat_record.owner_user_id == target.user_id:
                raise PermissionDeniedError(self.message_service.target_is_owner())
            target_level = await self._get_public_level(chat_id, target.user_id)
            if target_level >= caller_level:
                raise PermissionDeniedError(self.message_service.target_same_or_higher_level())
        return caller_level, target_level

    async def mutate_level(
        self,
        *,
        bot: Bot,
        chat_id: int,
        actor: User,
        target: ResolvedUser,
        requested_level: int | None = None,
        requested_delta: int | None = None,
    ) -> int:
        caller_level, _ = await self.ensure_manage_levels_allowed(
            bot=bot,
            chat_id=chat_id,
            actor=actor,
            target=target,
        )
        current_level = await self._get_public_level(chat_id, target.user_id)
        new_level = self.resolve_requested_level(
            actor_level=caller_level,
            current_level=current_level,
            requested_level=requested_level,
            requested_delta=requested_delta,
        )

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
            await self.admin_levels_repo.set_level(
                chat_id=chat_id,
                user_id=target.user_id,
                admin_level=new_level,
                granted_by_user_id=actor.id,
                connection=connection,
            )
            await self.punishments_repo.add_entry(
                chat_id=chat_id,
                target_user_id=target.user_id,
                target_username=target.username,
                target_display_name=target.display_name,
                moderator_user_id=actor.id,
                moderator_username=actor.username,
                moderator_display_name=f"{actor.first_name} {actor.last_name or ''}".strip(),
                action_type="set_level",
                reason=f"Уровень установлен на {new_level}",
                duration_seconds=None,
                mute_until=None,
                is_active=False,
                extra_data_json=None,
                connection=connection,
            )
        return new_level

    def resolve_requested_level(
        self,
        *,
        actor_level: int,
        current_level: int,
        requested_level: int | None,
        requested_delta: int | None,
    ) -> int:
        max_allowed = self.max_manageable_assignment_for_actor(actor_level)

        if requested_level is not None:
            if requested_level > MAX_ASSIGNABLE_ADMIN_LEVEL:
                raise ValidationError(self.message_service.level_five_reserved())
            if requested_level > max_allowed:
                raise ValidationError(self.message_service.level_assignment_cap(max_allowed))
            return requested_level

        if requested_delta is None:
            raise ValidationError("❌ Не удалось определить новый уровень модерации.")

        new_level = current_level + requested_delta
        if new_level > MAX_ASSIGNABLE_ADMIN_LEVEL:
            raise ValidationError(self.message_service.level_five_reserved())
        if new_level > max_allowed:
            if requested_delta > 0:
                raise ValidationError(self.message_service.level_already_max_assignable(max_allowed))
            raise ValidationError(self.message_service.level_assignment_cap(max_allowed))
        if new_level < 0:
            raise ValidationError(self.message_service.level_already_min())
        return new_level

    def max_manageable_assignment_for_actor(self, actor_level: int) -> int:
        if actor_level >= 5:
            return MAX_ASSIGNABLE_ADMIN_LEVEL
        if actor_level >= 4:
            return LEVEL_FOUR_ASSIGNMENT_CAP
        return 0

    async def remove_level(self, *, bot: Bot, chat_id: int, actor: User, target: ResolvedUser) -> None:
        await self.ensure_manage_levels_allowed(bot=bot, chat_id=chat_id, actor=actor, target=target)
        async with self.database.transaction() as connection:
            await self.admin_levels_repo.remove_level(chat_id, target.user_id, connection=connection)
            await self.punishments_repo.add_entry(
                chat_id=chat_id,
                target_user_id=target.user_id,
                target_username=target.username,
                target_display_name=target.display_name,
                moderator_user_id=actor.id,
                moderator_username=actor.username,
                moderator_display_name=f"{actor.first_name} {actor.last_name or ''}".strip(),
                action_type="remove_level",
                reason="Уровень снят",
                duration_seconds=None,
                mute_until=None,
                is_active=False,
                extra_data_json=None,
                connection=connection,
            )

    async def list_moderators(self, *, bot: Bot, chat_id: int, actor: User) -> list[tuple[ResolvedUser, int]]:
        await self.ensure_manage_levels_allowed(bot=bot, chat_id=chat_id, actor=actor)
        rows = await self.admin_levels_repo.list_moderators(chat_id)
        result: list[tuple[ResolvedUser, int]] = []
        for row in rows:
            cached = await self.users_repo.get_by_user_id(row.user_id)
            identity = ResolvedUser(
                user_id=row.user_id,
                username=cached.username if cached else None,
                display_name=cached.display_name if cached else f"ID {row.user_id}",
                source="cache",
            )
            result.append((identity, row.admin_level))
        return result

    async def _ensure_actor_ready(self, bot: Bot, chat_id: int, actor: User, *, required_level: int) -> tuple[int, object | None]:
        actor_member = await safe_get_chat_member(bot, chat_id, actor.id)
        if actor_member is None or not is_active_chat_member(actor_member):
            raise PermissionDeniedError(self.message_service.caller_not_member())
        await self._maybe_refresh_owner_state(bot=bot, chat_id=chat_id, user_id=actor.id, member=actor_member)
        caller_level = await self._get_effective_level(chat_id, actor.id)
        if caller_level < required_level:
            raise PermissionDeniedError(self.message_service.insufficient_level(required_level))
        return caller_level, actor_member

    async def _ensure_bot_can_do_action(self, bot: Bot, chat_id: int, action: str) -> None:
        if action not in {"mute", "unmute", "kick", "ban", "unban"}:
            return
        bot_member = await safe_get_chat_member(bot, chat_id, bot.id)
        if not member_has_restrict_rights(bot_member):
            raise PermissionDeniedError(self.message_service.bot_lacks_rights())

    async def _get_effective_level(self, chat_id: int, user_id: int) -> int:
        if self.is_system_owner(user_id):
            return 5
        return await self._get_public_level(chat_id, user_id)

    async def _get_public_level(self, chat_id: int, user_id: int) -> int:
        stored_level = await self._get_stored_level(chat_id, user_id)
        chat_record = await self.chats_repo.get_chat(chat_id)
        if chat_record and chat_record.owner_user_id == user_id:
            return max(stored_level, 5)
        return stored_level

    async def _get_stored_level(self, chat_id: int, user_id: int) -> int:
        return await self.admin_levels_repo.get_level(chat_id, user_id)

    def is_system_owner(self, user_id: int) -> bool:
        return self.system_owner_user_id is not None and user_id == self.system_owner_user_id

    async def _maybe_refresh_owner_state(
        self,
        *,
        bot: Bot | None,
        chat_id: int,
        user_id: int,
        member=None,
    ) -> None:
        if self.is_system_owner(user_id):
            return

        chat_record = await self.chats_repo.get_chat(chat_id)
        if chat_record and chat_record.owner_user_id == user_id:
            return

        resolved_member = member
        if resolved_member is None and bot is not None:
            resolved_member = await safe_get_chat_member(bot, chat_id, user_id)

        if resolved_member is not None and getattr(resolved_member, "status", None) == ChatMemberStatus.CREATOR:
            if self.chat_service is not None and getattr(resolved_member, "user", None) is not None:
                owner_user = resolved_member.user
                await self.chat_service.promote_chat_owner(
                    chat_id=chat_id,
                    user_id=owner_user.id,
                    username=owner_user.username,
                    display_name=f"{owner_user.first_name} {owner_user.last_name or ''}".strip(),
                    first_name=owner_user.first_name,
                    last_name=owner_user.last_name,
                )
            return

        if (chat_record is None or chat_record.owner_user_id is None) and bot is not None and self.chat_service is not None:
            await self.chat_service.ensure_owner_snapshot(bot, chat_id=chat_id)
