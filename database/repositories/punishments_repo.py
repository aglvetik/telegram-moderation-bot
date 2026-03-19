from __future__ import annotations

import aiosqlite

from database.db import Database
from database.models import PunishmentRecord
from utils.formatters import to_iso, utc_now


class PunishmentsRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def add_entry(
        self,
        *,
        chat_id: int,
        target_user_id: int,
        target_username: str | None,
        target_display_name: str | None,
        moderator_user_id: int | None,
        moderator_username: str | None,
        moderator_display_name: str | None,
        action_type: str,
        reason: str | None = None,
        duration_seconds: int | None = None,
        mute_until: str | None = None,
        is_active: bool = False,
        extra_data_json: str | None = None,
        connection: aiosqlite.Connection | None = None,
    ) -> None:
        await self.database.execute(
            """
            INSERT INTO punishments_history(
                chat_id,
                target_user_id,
                target_username,
                target_display_name,
                moderator_user_id,
                moderator_username,
                moderator_display_name,
                action_type,
                reason,
                duration_seconds,
                mute_until,
                created_at,
                is_active,
                extra_data_json
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                chat_id,
                target_user_id,
                target_username,
                target_display_name,
                moderator_user_id,
                moderator_username,
                moderator_display_name,
                action_type,
                reason,
                duration_seconds,
                mute_until,
                to_iso(utc_now()),
                1 if is_active else 0,
                extra_data_json,
            ),
            connection=connection,
        )

    async def list_user_history(
        self,
        *,
        chat_id: int,
        target_user_id: int,
        limit: int,
        connection: aiosqlite.Connection | None = None,
    ) -> list[PunishmentRecord]:
        rows = await self.database.fetchall(
            """
            SELECT * FROM punishments_history
            WHERE chat_id = ? AND target_user_id = ?
            ORDER BY created_at DESC
            LIMIT ?;
            """,
            (chat_id, target_user_id, limit),
            connection=connection,
        )
        return [PunishmentRecord.from_row(row) for row in rows]

    async def deactivate_entries(
        self,
        *,
        chat_id: int,
        target_user_id: int,
        action_types: tuple[str, ...],
        connection: aiosqlite.Connection | None = None,
    ) -> None:
        placeholders = ", ".join("?" for _ in action_types)
        await self.database.execute(
            f"""
            UPDATE punishments_history
            SET is_active = 0
            WHERE chat_id = ? AND target_user_id = ? AND action_type IN ({placeholders}) AND is_active = 1;
            """,
            (chat_id, target_user_id, *action_types),
            connection=connection,
        )

    async def cleanup_old_records(self, cutoff_iso: str, *, connection: aiosqlite.Connection | None = None) -> None:
        await self.database.execute(
            "DELETE FROM punishments_history WHERE created_at < ?;",
            (cutoff_iso,),
            connection=connection,
        )

    async def migrate_chat(self, old_chat_id: int, new_chat_id: int, *, connection: aiosqlite.Connection | None = None) -> None:
        await self.database.execute(
            "UPDATE punishments_history SET chat_id = ? WHERE chat_id = ?;",
            (new_chat_id, old_chat_id),
            connection=connection,
        )
