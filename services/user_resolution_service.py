from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from aiogram import Bot
from aiogram.types import ChatMember, ChatMemberUpdated, Message, User

from database.db import Database
from database.repositories.chats_repo import ChatsRepository
from database.repositories.message_refs_repo import MessageRefsRepository
from database.repositories.users_repo import UsersRepository
from services.parser_service import ParsedCommand, TargetInput
from utils.exceptions import TargetResolutionError
from utils.formatters import utc_now
from utils.telegram_helpers import build_user_display_name, safe_get_chat_member, timestamp_to_datetime

if TYPE_CHECKING:
    from services.message_service import MessageService


@dataclass(slots=True)
class ResolvedUser:
    user_id: int
    display_name: str
    username: str | None = None
    source: str = "unknown"
    member: ChatMember | None = None


class UserResolutionService:
    """Persists seen identities and resolves targets from replies, cache, and lightweight message refs."""

    def __init__(
        self,
        *,
        database: Database,
        chats_repo: ChatsRepository,
        users_repo: UsersRepository,
        message_refs_repo: MessageRefsRepository,
        message_service: MessageService,
    ) -> None:
        self.database = database
        self.chats_repo = chats_repo
        self.users_repo = users_repo
        self.message_refs_repo = message_refs_repo
        self.message_service = message_service
        self.logger = logging.getLogger(__name__)

    async def ingest_message(self, message: Message) -> None:
        async with self.database.transaction() as connection:
            await self.chats_repo.upsert_chat(
                chat_id=message.chat.id,
                chat_type=message.chat.type,
                title=message.chat.title,
                settings=None,
                connection=connection,
            )
            await self._upsert_user(message.from_user, chat_id=message.chat.id, connection=connection)

            reply = message.reply_to_message
            reply_user = getattr(reply, "from_user", None)
            await self._upsert_user(reply_user, chat_id=message.chat.id, connection=connection)

            if message.from_user is not None:
                await self.message_refs_repo.upsert_message_ref(
                    chat_id=message.chat.id,
                    message_id=message.message_id,
                    sender_user_id=message.from_user.id,
                    sender_username=message.from_user.username,
                    sender_display_name=build_user_display_name(message.from_user),
                    reply_to_message_id=getattr(reply, "message_id", None),
                    message_date=timestamp_to_datetime(message.date) or utc_now(),
                    connection=connection,
                )

    async def ingest_chat_member_update(self, event: ChatMemberUpdated) -> None:
        async with self.database.transaction() as connection:
            await self.chats_repo.upsert_chat(
                chat_id=event.chat.id,
                chat_type=event.chat.type,
                title=event.chat.title,
                settings=None,
                connection=connection,
            )
            await self._upsert_user(event.from_user, chat_id=event.chat.id, connection=connection)
            await self._upsert_user(event.new_chat_member.user, chat_id=event.chat.id, connection=connection)

    async def remember_resolved(self, resolved: ResolvedUser, *, chat_id: int | None = None) -> None:
        await self.users_repo.upsert_user(
            user_id=resolved.user_id,
            username=resolved.username,
            display_name=resolved.display_name,
            first_name=None,
            last_name=None,
            last_seen_chat_id=chat_id,
        )

    def build_actor(self, user: User) -> ResolvedUser:
        return ResolvedUser(
            user_id=user.id,
            username=user.username,
            display_name=build_user_display_name(user),
            source="actor",
        )

    async def resolve_target(self, bot: Bot, message: Message, parsed: ParsedCommand) -> ResolvedUser:
        reply_target: ResolvedUser | None = None
        explicit_target: ResolvedUser | None = None

        if message.reply_to_message:
            reply_target = await self._resolve_reply_target(bot, message)
        if parsed.explicit_target is not None:
            explicit_target = await self._resolve_explicit_target(bot, message.chat.id, parsed.explicit_target)

        resolved = self._merge_targets(reply_target=reply_target, explicit_target=explicit_target)
        if resolved is None:
            raise TargetResolutionError(self.message_service.target_not_found())

        await self.remember_resolved(resolved, chat_id=message.chat.id)
        return resolved

    async def resolve_optional_target(self, bot: Bot, message: Message, parsed: ParsedCommand) -> ResolvedUser | None:
        if message.reply_to_message or parsed.explicit_target is not None:
            return await self.resolve_target(bot, message, parsed)
        return None

    async def resolve_user_id(self, bot: Bot, chat_id: int, user_id: int) -> ResolvedUser:
        cached = await self.users_repo.get_by_user_id(user_id)
        member = await safe_get_chat_member(bot, chat_id, user_id)
        if member and getattr(member, "user", None):
            user = member.user
            return ResolvedUser(
                user_id=user.id,
                username=user.username,
                display_name=build_user_display_name(user),
                source="user_id",
                member=member,
            )
        if cached:
            return ResolvedUser(
                user_id=cached.user_id,
                username=cached.username,
                display_name=cached.display_name,
                source="user_id",
                member=member,
            )
        return ResolvedUser(user_id=user_id, username=None, display_name=f"ID {user_id}", source="user_id", member=member)

    async def _resolve_reply_target(self, bot: Bot, message: Message) -> ResolvedUser:
        reply = message.reply_to_message
        reply_user = getattr(reply, "from_user", None)
        if reply_user is not None:
            member = await safe_get_chat_member(bot, message.chat.id, reply_user.id)
            return ResolvedUser(
                user_id=reply_user.id,
                username=reply_user.username,
                display_name=build_user_display_name(reply_user),
                source="reply",
                member=member,
            )

        reply_message_id = getattr(reply, "message_id", None)
        if reply_message_id is not None:
            cached_ref = await self.message_refs_repo.get_message_ref(chat_id=message.chat.id, message_id=reply_message_id)
            if cached_ref and cached_ref.sender_user_id is not None:
                resolved = await self.resolve_user_id(bot, message.chat.id, cached_ref.sender_user_id)
                if resolved.display_name.startswith("ID ") and cached_ref.sender_display_name:
                    resolved.display_name = cached_ref.sender_display_name
                if resolved.username is None:
                    resolved.username = cached_ref.sender_username
                resolved.source = "message_ref"
                return resolved

        raise TargetResolutionError(self.message_service.target_not_found())

    async def _resolve_explicit_target(self, bot: Bot, chat_id: int, target: TargetInput) -> ResolvedUser:
        if target.user_id is not None:
            return await self.resolve_user_id(bot, chat_id, target.user_id)

        if target.username is None:
            raise TargetResolutionError(self.message_service.target_not_found())

        cached = await self.users_repo.get_by_username(target.username)
        if cached is None:
            raise TargetResolutionError(self.message_service.username_resolution_failed())

        member = await safe_get_chat_member(bot, chat_id, cached.user_id)
        return ResolvedUser(
            user_id=cached.user_id,
            username=cached.username,
            display_name=cached.display_name,
            source="username",
            member=member,
        )

    def _merge_targets(
        self,
        *,
        reply_target: ResolvedUser | None,
        explicit_target: ResolvedUser | None,
    ) -> ResolvedUser | None:
        if reply_target is None:
            return explicit_target
        if explicit_target is None:
            return reply_target
        if reply_target.user_id != explicit_target.user_id:
            raise TargetResolutionError(self.message_service.conflicting_targets())
        return ResolvedUser(
            user_id=reply_target.user_id,
            username=reply_target.username or explicit_target.username,
            display_name=reply_target.display_name if reply_target.display_name and not reply_target.display_name.startswith("ID ") else explicit_target.display_name,
            source="reply+explicit",
            member=reply_target.member or explicit_target.member,
        )

    async def hydrate_display_name(self, user_id: int) -> str:
        cached = await self.users_repo.get_by_user_id(user_id)
        if cached:
            return cached.display_name
        return f"ID {user_id}"

    async def hydrate_identity(self, user_id: int) -> ResolvedUser:
        cached = await self.users_repo.get_by_user_id(user_id)
        if cached:
            return ResolvedUser(
                user_id=user_id,
                username=cached.username,
                display_name=cached.display_name,
                source="cache",
            )
        return ResolvedUser(user_id=user_id, display_name=f"ID {user_id}", source="cache")

    async def _upsert_user(
        self,
        user: User | None,
        *,
        chat_id: int | None,
        connection,
    ) -> None:
        if user is None:
            return
        await self.users_repo.upsert_user(
            user_id=user.id,
            username=user.username,
            display_name=build_user_display_name(user),
            first_name=user.first_name,
            last_name=user.last_name,
            last_seen_chat_id=chat_id,
            connection=connection,
        )
