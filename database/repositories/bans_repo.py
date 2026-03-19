from __future__ import annotations

from datetime import datetime

import aiosqlite

from database.db import Database
from database.models import BanRecord
from utils.formatters import to_iso


class BansRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def create_active_ban(
        self,
        *,
        chat_id: int,
        user_id: int,
        banned_at: datetime,
        reason: str | None,
        moderator_user_id: int | None,
        connection: aiosqlite.Connection | None = None,
    ) -> None:
        await self.database.execute(
            """
            INSERT INTO bans(chat_id, user_id, banned_at, reason, moderator_user_id, is_active)
            VALUES(?, ?, ?, ?, ?, 1);
            """,
            (chat_id, user_id, to_iso(banned_at), reason, moderator_user_id),
            connection=connection,
        )

    async def get_active_ban(
        self,
        chat_id: int,
        user_id: int,
        *,
        connection: aiosqlite.Connection | None = None,
    ) -> BanRecord | None:
        row = await self.database.fetchone(
            """
            SELECT * FROM bans
            WHERE chat_id = ? AND user_id = ? AND is_active = 1
            ORDER BY banned_at DESC
            LIMIT 1;
            """,
            (chat_id, user_id),
            connection=connection,
        )
        return BanRecord.from_row(row) if row else None

    async def deactivate_ban(
        self,
        *,
        chat_id: int,
        user_id: int,
        connection: aiosqlite.Connection | None = None,
    ) -> None:
        await self.database.execute(
            "UPDATE bans SET is_active = 0 WHERE chat_id = ? AND user_id = ? AND is_active = 1;",
            (chat_id, user_id),
            connection=connection,
        )

    async def cleanup_old_records(self, cutoff_iso: str, *, connection: aiosqlite.Connection | None = None) -> None:
        await self.database.execute(
            "DELETE FROM bans WHERE is_active = 0 AND banned_at < ?;",
            (cutoff_iso,),
            connection=connection,
        )

    async def migrate_chat(self, old_chat_id: int, new_chat_id: int, *, connection: aiosqlite.Connection | None = None) -> None:
        await self.database.execute(
            "UPDATE bans SET chat_id = ? WHERE chat_id = ?;",
            (new_chat_id, old_chat_id),
            connection=connection,
        )
