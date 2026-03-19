from __future__ import annotations

import aiosqlite

from database.db import Database
from database.models import AdminLevelRecord
from utils.formatters import to_iso, utc_now


class AdminLevelsRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def get_level(self, chat_id: int, user_id: int, *, connection: aiosqlite.Connection | None = None) -> int:
        row = await self.database.fetchone(
            "SELECT admin_level FROM admin_levels WHERE chat_id = ? AND user_id = ?;",
            (chat_id, user_id),
            connection=connection,
        )
        return int(row["admin_level"]) if row else 0

    async def set_level(
        self,
        *,
        chat_id: int,
        user_id: int,
        admin_level: int,
        granted_by_user_id: int | None,
        connection: aiosqlite.Connection | None = None,
    ) -> None:
        now = to_iso(utc_now())
        await self.database.execute(
            """
            INSERT INTO admin_levels(chat_id, user_id, admin_level, granted_by_user_id, granted_at, updated_at)
            VALUES(?, ?, ?, ?, ?, ?)
            ON CONFLICT(chat_id, user_id) DO UPDATE SET
                admin_level=excluded.admin_level,
                granted_by_user_id=excluded.granted_by_user_id,
                updated_at=excluded.updated_at;
            """,
            (chat_id, user_id, admin_level, granted_by_user_id, now, now),
            connection=connection,
        )

    async def remove_level(self, chat_id: int, user_id: int, *, connection: aiosqlite.Connection | None = None) -> None:
        await self.database.execute(
            "DELETE FROM admin_levels WHERE chat_id = ? AND user_id = ?;",
            (chat_id, user_id),
            connection=connection,
        )

    async def get_record(
        self,
        chat_id: int,
        user_id: int,
        *,
        connection: aiosqlite.Connection | None = None,
    ) -> AdminLevelRecord | None:
        row = await self.database.fetchone(
            "SELECT * FROM admin_levels WHERE chat_id = ? AND user_id = ?;",
            (chat_id, user_id),
            connection=connection,
        )
        return AdminLevelRecord.from_row(row) if row else None

    async def list_moderators(self, chat_id: int, *, connection: aiosqlite.Connection | None = None) -> list[AdminLevelRecord]:
        rows = await self.database.fetchall(
            """
            SELECT * FROM admin_levels
            WHERE chat_id = ? AND admin_level >= 1
            ORDER BY admin_level DESC, updated_at DESC;
            """,
            (chat_id,),
            connection=connection,
        )
        return [AdminLevelRecord.from_row(row) for row in rows]

    async def migrate_chat(self, old_chat_id: int, new_chat_id: int, *, connection: aiosqlite.Connection | None = None) -> None:
        await self.database.execute(
            "UPDATE admin_levels SET chat_id = ? WHERE chat_id = ?;",
            (new_chat_id, old_chat_id),
            connection=connection,
        )
