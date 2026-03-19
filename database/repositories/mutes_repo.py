from __future__ import annotations

from datetime import datetime

import aiosqlite

from database.db import Database
from database.models import ActiveMuteRecord
from utils.formatters import to_iso


class MutesRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def create_active_mute(
        self,
        *,
        chat_id: int,
        user_id: int,
        started_at: datetime,
        ends_at: datetime | None,
        reason: str | None,
        moderator_user_id: int | None,
        connection: aiosqlite.Connection | None = None,
    ) -> None:
        await self.database.execute(
            """
            INSERT INTO active_mutes(chat_id, user_id, started_at, ends_at, reason, moderator_user_id, is_active)
            VALUES(?, ?, ?, ?, ?, ?, 1);
            """,
            (chat_id, user_id, to_iso(started_at), to_iso(ends_at), reason, moderator_user_id),
            connection=connection,
        )

    async def get_active_mute(
        self,
        chat_id: int,
        user_id: int,
        *,
        connection: aiosqlite.Connection | None = None,
    ) -> ActiveMuteRecord | None:
        row = await self.database.fetchone(
            """
            SELECT * FROM active_mutes
            WHERE chat_id = ? AND user_id = ? AND is_active = 1
            ORDER BY started_at DESC
            LIMIT 1;
            """,
            (chat_id, user_id),
            connection=connection,
        )
        return ActiveMuteRecord.from_row(row) if row else None

    async def list_expired_mutes(
        self,
        reference_iso: str,
        *,
        connection: aiosqlite.Connection | None = None,
    ) -> list[ActiveMuteRecord]:
        rows = await self.database.fetchall(
            """
            SELECT * FROM active_mutes
            WHERE is_active = 1 AND ends_at IS NOT NULL AND ends_at <= ?
            ORDER BY ends_at ASC;
            """,
            (reference_iso,),
            connection=connection,
        )
        return [ActiveMuteRecord.from_row(row) for row in rows]

    async def list_active_mutes(
        self,
        *,
        chat_id: int | None = None,
        limit: int | None = None,
        connection: aiosqlite.Connection | None = None,
    ) -> list[ActiveMuteRecord]:
        query = "SELECT * FROM active_mutes WHERE is_active = 1"
        params: list[int] = []
        if chat_id is not None:
            query += " AND chat_id = ?"
            params.append(chat_id)
        query += " ORDER BY CASE WHEN ends_at IS NULL THEN 1 ELSE 0 END, ends_at ASC, started_at ASC"
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        rows = await self.database.fetchall(query + ";", tuple(params), connection=connection)
        return [ActiveMuteRecord.from_row(row) for row in rows]

    async def complete_mute(
        self,
        *,
        chat_id: int,
        user_id: int,
        connection: aiosqlite.Connection | None = None,
    ) -> None:
        await self.database.execute(
            "UPDATE active_mutes SET is_active = 0 WHERE chat_id = ? AND user_id = ? AND is_active = 1;",
            (chat_id, user_id),
            connection=connection,
        )

    async def cleanup_old_records(self, cutoff_iso: str, *, connection: aiosqlite.Connection | None = None) -> None:
        await self.database.execute(
            "DELETE FROM active_mutes WHERE is_active = 0 AND COALESCE(ends_at, started_at) < ?;",
            (cutoff_iso,),
            connection=connection,
        )

    async def migrate_chat(self, old_chat_id: int, new_chat_id: int, *, connection: aiosqlite.Connection | None = None) -> None:
        await self.database.execute(
            "UPDATE active_mutes SET chat_id = ? WHERE chat_id = ?;",
            (new_chat_id, old_chat_id),
            connection=connection,
        )
