from __future__ import annotations

import aiosqlite

from database.db import Database
from database.models import UserCacheRecord
from utils.formatters import to_iso, utc_now
from utils.validators import normalize_username


class UsersRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def upsert_user(
        self,
        *,
        user_id: int,
        username: str | None,
        display_name: str,
        first_name: str | None = None,
        last_name: str | None = None,
        last_seen_chat_id: int | None = None,
        connection: aiosqlite.Connection | None = None,
    ) -> None:
        normalized_username = normalize_username(username)
        now_iso = to_iso(utc_now())
        if normalized_username:
            await self.database.execute(
                """
                UPDATE users_cache
                SET username = NULL, updated_at = ?
                WHERE lower(username) = ? AND user_id != ?;
                """,
                (now_iso, normalized_username, user_id),
                connection=connection,
            )

        await self.database.execute(
            """
            INSERT INTO users_cache(
                user_id,
                username,
                display_name,
                first_name,
                last_name,
                first_seen_at,
                last_seen_at,
                updated_at,
                last_seen_chat_id
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username=excluded.username,
                display_name=excluded.display_name,
                first_name=excluded.first_name,
                last_name=excluded.last_name,
                last_seen_at=excluded.last_seen_at,
                updated_at=excluded.updated_at,
                last_seen_chat_id=COALESCE(excluded.last_seen_chat_id, users_cache.last_seen_chat_id);
            """,
            (
                user_id,
                normalized_username,
                display_name,
                first_name,
                last_name,
                now_iso,
                now_iso,
                now_iso,
                last_seen_chat_id,
            ),
            connection=connection,
        )

    async def get_by_user_id(
        self,
        user_id: int,
        *,
        connection: aiosqlite.Connection | None = None,
    ) -> UserCacheRecord | None:
        row = await self.database.fetchone(
            "SELECT * FROM users_cache WHERE user_id = ?;",
            (user_id,),
            connection=connection,
        )
        return UserCacheRecord.from_row(row) if row else None

    async def get_by_username(
        self,
        username: str,
        *,
        connection: aiosqlite.Connection | None = None,
    ) -> UserCacheRecord | None:
        normalized = normalize_username(username)
        if normalized is None:
            return None
        row = await self.database.fetchone(
            "SELECT * FROM users_cache WHERE lower(username) = ?;",
            (normalized,),
            connection=connection,
        )
        return UserCacheRecord.from_row(row) if row else None
