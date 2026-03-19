from __future__ import annotations

import json

import aiosqlite

from database.db import Database
from database.models import ChatRecord
from utils.formatters import to_iso, utc_now


class ChatsRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def upsert_chat(
        self,
        *,
        chat_id: int,
        chat_type: str,
        title: str | None,
        owner_user_id: int | None = None,
        settings: dict | None = None,
        connection: aiosqlite.Connection | None = None,
    ) -> None:
        now = to_iso(utc_now())
        settings_json = json.dumps(settings, ensure_ascii=False) if settings is not None else None
        await self.database.execute(
            """
            INSERT INTO chats(chat_id, chat_type, title, owner_user_id, bot_added_at, is_active, settings_json)
            VALUES(?, ?, ?, ?, ?, 1, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                chat_type=excluded.chat_type,
                title=excluded.title,
                owner_user_id=COALESCE(excluded.owner_user_id, chats.owner_user_id),
                is_active=1,
                settings_json=COALESCE(excluded.settings_json, chats.settings_json);
            """,
            (chat_id, chat_type, title, owner_user_id, now, settings_json),
            connection=connection,
        )

    async def get_chat(self, chat_id: int, *, connection: aiosqlite.Connection | None = None) -> ChatRecord | None:
        row = await self.database.fetchone(
            "SELECT * FROM chats WHERE chat_id = ?;",
            (chat_id,),
            connection=connection,
        )
        return ChatRecord.from_row(row) if row else None

    async def set_chat_active(self, chat_id: int, is_active: bool, *, connection: aiosqlite.Connection | None = None) -> None:
        await self.database.execute(
            "UPDATE chats SET is_active = ? WHERE chat_id = ?;",
            (1 if is_active else 0, chat_id),
            connection=connection,
        )

    async def update_owner(self, chat_id: int, owner_user_id: int | None, *, connection: aiosqlite.Connection | None = None) -> None:
        await self.database.execute(
            "UPDATE chats SET owner_user_id = ? WHERE chat_id = ?;",
            (owner_user_id, chat_id),
            connection=connection,
        )

    async def migrate_chat_id(self, old_chat_id: int, new_chat_id: int, *, connection: aiosqlite.Connection | None = None) -> None:
        old_chat = await self.get_chat(old_chat_id, connection=connection)
        if old_chat is None:
            await self.upsert_chat(
                chat_id=new_chat_id,
                chat_type="supergroup",
                title=None,
                owner_user_id=None,
                settings={},
                connection=connection,
            )
            return
        await self.database.execute(
            """
            INSERT INTO chats(chat_id, chat_type, title, owner_user_id, bot_added_at, is_active, settings_json)
            VALUES(?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                chat_type=excluded.chat_type,
                title=excluded.title,
                owner_user_id=excluded.owner_user_id,
                bot_added_at=excluded.bot_added_at,
                is_active=excluded.is_active,
                settings_json=excluded.settings_json;
            """,
            (
                new_chat_id,
                old_chat.chat_type,
                old_chat.title,
                old_chat.owner_user_id,
                to_iso(old_chat.bot_added_at),
                1 if old_chat.is_active else 0,
                old_chat.settings_json,
            ),
            connection=connection,
        )

    async def delete_chat(self, chat_id: int, *, connection: aiosqlite.Connection | None = None) -> None:
        await self.database.execute("DELETE FROM chats WHERE chat_id = ?;", (chat_id,), connection=connection)
