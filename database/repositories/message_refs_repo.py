from __future__ import annotations

from datetime import datetime

import aiosqlite

from database.db import Database
from database.models import MessageRefRecord
from utils.formatters import to_iso
from utils.validators import normalize_username


class MessageRefsRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def upsert_message_ref(
        self,
        *,
        chat_id: int,
        message_id: int,
        sender_user_id: int | None,
        sender_username: str | None,
        sender_display_name: str | None,
        reply_to_message_id: int | None,
        message_date: datetime,
        connection: aiosqlite.Connection | None = None,
    ) -> None:
        await self.database.execute(
            """
            INSERT INTO message_refs(
                chat_id,
                message_id,
                sender_user_id,
                sender_username,
                sender_display_name,
                reply_to_message_id,
                message_date
            )
            VALUES(?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(chat_id, message_id) DO UPDATE SET
                sender_user_id=excluded.sender_user_id,
                sender_username=excluded.sender_username,
                sender_display_name=excluded.sender_display_name,
                reply_to_message_id=excluded.reply_to_message_id,
                message_date=excluded.message_date;
            """,
            (
                chat_id,
                message_id,
                sender_user_id,
                normalize_username(sender_username),
                sender_display_name,
                reply_to_message_id,
                to_iso(message_date),
            ),
            connection=connection,
        )

    async def get_message_ref(
        self,
        *,
        chat_id: int,
        message_id: int,
        connection: aiosqlite.Connection | None = None,
    ) -> MessageRefRecord | None:
        row = await self.database.fetchone(
            "SELECT * FROM message_refs WHERE chat_id = ? AND message_id = ?;",
            (chat_id, message_id),
            connection=connection,
        )
        return MessageRefRecord.from_row(row) if row else None

    async def cleanup_old_records(self, cutoff_iso: str, *, connection: aiosqlite.Connection | None = None) -> None:
        await self.database.execute(
            "DELETE FROM message_refs WHERE message_date < ?;",
            (cutoff_iso,),
            connection=connection,
        )

    async def migrate_chat(self, old_chat_id: int, new_chat_id: int, *, connection: aiosqlite.Connection | None = None) -> None:
        await self.database.execute(
            "UPDATE message_refs SET chat_id = ? WHERE chat_id = ?;",
            (new_chat_id, old_chat_id),
            connection=connection,
        )
