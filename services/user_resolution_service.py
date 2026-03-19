from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from aiogram import Bot
from aiogram.types import ChatMember, ChatMemberUpdated, Message, User

from database.db import Database
from database.repositories.chats_repo import ChatsRepository
from database.repositories.message_refs_repo import MessageRefsRepository
from database.repositories.users_repo import UsersRepository
from services.parser_service import ParsedCommand, TargetInput
from utils.exceptions import TargetResolutionError
from utils.formatters import build_display_name, utc_now
from utils.telegram_helpers import build_user_display_name, safe_get_chat_member, timestamp_to_datetime


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
    ) -> None:
        self.database = database
        self.chats_repo = chats_repo
        self.users_repo = users_repo
        self.message_refs_repo = message_refs_repo
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
        if message.reply_to_message:
            resolved = await self._resolve_reply_target(bot, message)
            await self.remember_resolved(resolved, chat_id=message.chat.id)
            return resolved

        if parsed.explicit_target is None:
            raise TargetResolutionError("❌ Не удалось определить пользователя.\nИспользуйте reply, username или user_id.")

        resolved = await self._resolve_explicit_target(bot, message.chat.id, parsed.explicit_target)
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

        raise TargetResolutionError("❌ Не удалось определить пользователя.\nПопробуйте команду по username или user_id.")

    async def _resolve_explicit_target(self, bot: Bot, chat_id: int, target: TargetInput) -> ResolvedUser:
        if target.user_id is not None:
            return await self.resolve_user_id(bot, chat_id, target.user_id)

        if target.username is None:
            raise TargetResolutionError("❌ Не удалось определить пользователя.\nИспользуйте reply, username или user_id.")

        cached = await self.users_repo.get_by_username(target.username)
        if cached is None:
            raise TargetResolutionError(
                "❌ Не удалось найти пользователя по username.\n"
                "Возможно, он недоступен боту. Попробуйте reply или user_id."
            )

        member = await safe_get_chat_member(bot, chat_id, cached.user_id)
        return ResolvedUser(
            user_id=cached.user_id,
            username=cached.username,
            display_name=cached.display_name,
            source="username",
            member=member,
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
