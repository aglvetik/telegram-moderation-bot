from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.enums import ChatMemberStatus, ChatType

from database.db import Database
from database.repositories.admin_levels_repo import AdminLevelsRepository
from database.repositories.bans_repo import BansRepository
from database.repositories.chats_repo import ChatsRepository
from database.repositories.message_refs_repo import MessageRefsRepository
from database.repositories.mutes_repo import MutesRepository
from database.repositories.punishments_repo import PunishmentsRepository
from database.repositories.users_repo import UsersRepository
from utils.telegram_helpers import build_user_display_name, call_with_retry


class ChatService:
    def __init__(
        self,
        *,
        database: Database,
        chats_repo: ChatsRepository,
        admin_levels_repo: AdminLevelsRepository,
        punishments_repo: PunishmentsRepository,
        mutes_repo: MutesRepository,
        bans_repo: BansRepository,
        users_repo: UsersRepository,
        message_refs_repo: MessageRefsRepository,
        retry_config,
    ) -> None:
        self.database = database
        self.chats_repo = chats_repo
        self.admin_levels_repo = admin_levels_repo
        self.punishments_repo = punishments_repo
        self.mutes_repo = mutes_repo
        self.bans_repo = bans_repo
        self.users_repo = users_repo
        self.message_refs_repo = message_refs_repo
        self.retry_config = retry_config
        self.logger = logging.getLogger(__name__)

    async def register_chat(self, bot: Bot, *, chat_id: int, chat_type: str, title: str | None) -> int | None:
        await self.chats_repo.upsert_chat(
            chat_id=chat_id,
            chat_type=chat_type,
            title=title,
            owner_user_id=None,
            settings={},
        )

        owner_user_id: int | None = None
        if chat_type in {ChatType.GROUP, ChatType.SUPERGROUP}:
            owner_user_id = await self._refresh_owner_and_admins(bot, chat_id)
        return owner_user_id

    async def ensure_owner_snapshot(self, bot: Bot, *, chat_id: int) -> int | None:
        chat_record = await self.chats_repo.get_chat(chat_id)
        if chat_record is None:
            try:
                chat = await call_with_retry(
                    lambda: bot.get_chat(chat_id),
                    logger=self.logger,
                    retry=self.retry_config,
                    context=f"get_chat:{chat_id}",
                )
            except Exception:
                self.logger.warning("Could not load chat metadata for owner refresh in chat %s", chat_id)
                return None

            await self.chats_repo.upsert_chat(
                chat_id=chat_id,
                chat_type=chat.type,
                title=getattr(chat, "title", None),
                owner_user_id=None,
                settings={},
            )
            chat_record = await self.chats_repo.get_chat(chat_id)

        if chat_record is None or chat_record.chat_type not in {ChatType.GROUP, ChatType.SUPERGROUP}:
            return chat_record.owner_user_id if chat_record else None
        if chat_record.owner_user_id is not None:
            return chat_record.owner_user_id
        return await self._refresh_owner_and_admins(bot, chat_id)

    async def deactivate_chat(self, chat_id: int) -> None:
        await self.chats_repo.set_chat_active(chat_id, False)

    async def migrate_chat(self, old_chat_id: int, new_chat_id: int) -> None:
        self.logger.info("Migrating chat %s -> %s", old_chat_id, new_chat_id)
        async with self.database.transaction() as connection:
            await self.chats_repo.migrate_chat_id(old_chat_id, new_chat_id, connection=connection)
            await self.admin_levels_repo.migrate_chat(old_chat_id, new_chat_id, connection=connection)
            await self.punishments_repo.migrate_chat(old_chat_id, new_chat_id, connection=connection)
            await self.mutes_repo.migrate_chat(old_chat_id, new_chat_id, connection=connection)
            await self.bans_repo.migrate_chat(old_chat_id, new_chat_id, connection=connection)
            await self.message_refs_repo.migrate_chat(old_chat_id, new_chat_id, connection=connection)
            await self.chats_repo.delete_chat(old_chat_id, connection=connection)

    async def _refresh_owner_and_admins(self, bot: Bot, chat_id: int) -> int | None:
        try:
            administrators = await call_with_retry(
                lambda: bot.get_chat_administrators(chat_id),
                logger=self.logger,
                retry=self.retry_config,
                context=f"get_chat_administrators:{chat_id}",
            )
        except Exception:
            self.logger.warning("Could not load administrators for chat %s", chat_id)
            return None

        owner_user_id: int | None = None
        admin_users: list[tuple[int, str | None, str, str | None, str | None, str]] = []
        for member in administrators:
            user = getattr(member, "user", None)
            if user is None:
                continue
            admin_users.append(
                (
                    user.id,
                    user.username,
                    build_user_display_name(user),
                    user.first_name,
                    user.last_name,
                    member.status,
                )
            )
            if member.status == ChatMemberStatus.CREATOR:
                owner_user_id = user.id

        async with self.database.transaction() as connection:
            for user_id, username, display_name, first_name, last_name, status in admin_users:
                await self._apply_member_role(
                    chat_id=chat_id,
                    user_id=user_id,
                    username=username,
                    display_name=display_name,
                    first_name=first_name,
                    last_name=last_name,
                    status=status,
                    connection=connection,
                )

            if owner_user_id is not None:
                await self.chats_repo.update_owner(chat_id, owner_user_id, connection=connection)
        return owner_user_id

    async def sync_member_role(
        self,
        *,
        chat_id: int,
        chat_type: str,
        title: str | None,
        user_id: int,
        username: str | None,
        display_name: str,
        first_name: str | None,
        last_name: str | None,
        status: str,
    ) -> None:
        if chat_type not in {ChatType.GROUP, ChatType.SUPERGROUP}:
            await self.chats_repo.upsert_chat(
                chat_id=chat_id,
                chat_type=chat_type,
                title=title,
                owner_user_id=None,
                settings={},
            )
            return

        async with self.database.transaction() as connection:
            await self.chats_repo.upsert_chat(
                chat_id=chat_id,
                chat_type=chat_type,
                title=title,
                owner_user_id=user_id if status == ChatMemberStatus.CREATOR else None,
                settings={},
                connection=connection,
            )
            await self._apply_member_role(
                chat_id=chat_id,
                user_id=user_id,
                username=username,
                display_name=display_name,
                first_name=first_name,
                last_name=last_name,
                status=status,
                connection=connection,
            )
            if status == ChatMemberStatus.CREATOR:
                await self.chats_repo.update_owner(chat_id, user_id, connection=connection)

    async def promote_chat_owner(
        self,
        *,
        chat_id: int,
        user_id: int,
        username: str | None,
        display_name: str,
        first_name: str | None,
        last_name: str | None,
    ) -> None:
        chat_record = await self.chats_repo.get_chat(chat_id)
        if chat_record is None:
            self.logger.debug("Skipping chat owner promotion for unknown chat %s", chat_id)
            return

        async with self.database.transaction() as connection:
            await self.users_repo.upsert_user(
                user_id=user_id,
                username=username,
                display_name=display_name,
                first_name=first_name,
                last_name=last_name,
                last_seen_chat_id=chat_id,
                connection=connection,
            )
            await self.chats_repo.update_owner(chat_id, user_id, connection=connection)
            await self.admin_levels_repo.set_level(
                chat_id=chat_id,
                user_id=user_id,
                admin_level=5,
                granted_by_user_id=None,
                connection=connection,
            )

    async def _apply_member_role(
        self,
        *,
        chat_id: int,
        user_id: int,
        username: str | None,
        display_name: str,
        first_name: str | None,
        last_name: str | None,
        status: str,
        connection,
    ) -> None:
        await self.users_repo.upsert_user(
            user_id=user_id,
            username=username,
            display_name=display_name,
            first_name=first_name,
            last_name=last_name,
            last_seen_chat_id=chat_id,
            connection=connection,
        )

        current_level = await self.admin_levels_repo.get_level(chat_id, user_id, connection=connection)
        desired_level = current_level
        if status == ChatMemberStatus.CREATOR:
            desired_level = max(desired_level, 5)
        elif current_level < 1 and status == ChatMemberStatus.ADMINISTRATOR:
            desired_level = 1

        if desired_level > current_level:
            await self.admin_levels_repo.set_level(
                chat_id=chat_id,
                user_id=user_id,
                admin_level=desired_level,
                granted_by_user_id=None,
                connection=connection,
            )
