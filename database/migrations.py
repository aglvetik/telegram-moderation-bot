from __future__ import annotations

import logging

import aiosqlite

from database.db import Database

LOGGER = logging.getLogger(__name__)


async def _table_columns(connection: aiosqlite.Connection, table_name: str) -> set[str]:
    cursor = await connection.execute(f"PRAGMA table_info({table_name});")
    rows = await cursor.fetchall()
    await cursor.close()
    return {row[1] for row in rows}


async def _ensure_column(
    connection: aiosqlite.Connection,
    *,
    table_name: str,
    column_name: str,
    ddl: str,
) -> None:
    columns = await _table_columns(connection, table_name)
    if column_name not in columns:
        await connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {ddl};")


async def run_migrations(database: Database) -> None:
    LOGGER.info("Running database migrations")
    async with database.transaction() as connection:
        await connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL
            );
            """
        )
        await connection.execute(
            """
            CREATE TABLE IF NOT EXISTS chats (
                chat_id INTEGER PRIMARY KEY,
                chat_type TEXT NOT NULL,
                title TEXT,
                owner_user_id INTEGER,
                bot_added_at TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                settings_json TEXT
            );
            """
        )
        await connection.execute(
            """
            CREATE TABLE IF NOT EXISTS users_cache (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                display_name TEXT NOT NULL,
                first_name TEXT,
                last_name TEXT,
                first_seen_at TEXT,
                last_seen_at TEXT,
                updated_at TEXT NOT NULL,
                last_seen_chat_id INTEGER
            );
            """
        )
        await _ensure_column(connection, table_name="users_cache", column_name="first_name", ddl="first_name TEXT")
        await _ensure_column(connection, table_name="users_cache", column_name="last_name", ddl="last_name TEXT")
        await _ensure_column(connection, table_name="users_cache", column_name="first_seen_at", ddl="first_seen_at TEXT")
        await _ensure_column(connection, table_name="users_cache", column_name="last_seen_at", ddl="last_seen_at TEXT")
        await connection.execute(
            """
            UPDATE users_cache
            SET first_seen_at = COALESCE(first_seen_at, updated_at),
                last_seen_at = COALESCE(last_seen_at, updated_at)
            WHERE first_seen_at IS NULL OR last_seen_at IS NULL;
            """
        )
        await connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_users_cache_username
            ON users_cache(lower(username))
            WHERE username IS NOT NULL;
            """
        )
        await connection.execute(
            """
            CREATE TABLE IF NOT EXISTS admin_levels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                admin_level INTEGER NOT NULL,
                granted_by_user_id INTEGER,
                granted_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(chat_id, user_id),
                FOREIGN KEY(chat_id) REFERENCES chats(chat_id) ON DELETE CASCADE
            );
            """
        )
        await connection.execute(
            """
            CREATE TABLE IF NOT EXISTS punishments_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                target_user_id INTEGER NOT NULL,
                target_username TEXT,
                target_display_name TEXT,
                moderator_user_id INTEGER,
                moderator_username TEXT,
                moderator_display_name TEXT,
                action_type TEXT NOT NULL,
                reason TEXT,
                duration_seconds INTEGER,
                mute_until TEXT,
                created_at TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 0,
                extra_data_json TEXT,
                FOREIGN KEY(chat_id) REFERENCES chats(chat_id) ON DELETE CASCADE
            );
            """
        )
        await connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_punishments_chat_target_created
            ON punishments_history(chat_id, target_user_id, created_at DESC);
            """
        )
        await connection.execute(
            """
            CREATE TABLE IF NOT EXISTS active_mutes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                started_at TEXT NOT NULL,
                ends_at TEXT NOT NULL,
                reason TEXT,
                moderator_user_id INTEGER,
                is_active INTEGER NOT NULL DEFAULT 1,
                FOREIGN KEY(chat_id) REFERENCES chats(chat_id) ON DELETE CASCADE
            );
            """
        )
        await connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_active_mutes_single_active
            ON active_mutes(chat_id, user_id)
            WHERE is_active = 1;
            """
        )
        await connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_active_mutes_ends_at
            ON active_mutes(chat_id, ends_at)
            WHERE is_active = 1;
            """
        )
        await connection.execute(
            """
            CREATE TABLE IF NOT EXISTS bans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                banned_at TEXT NOT NULL,
                ends_at TEXT,
                reason TEXT,
                moderator_user_id INTEGER,
                is_active INTEGER NOT NULL DEFAULT 1,
                FOREIGN KEY(chat_id) REFERENCES chats(chat_id) ON DELETE CASCADE
            );
            """
        )
        await _ensure_column(connection, table_name="bans", column_name="ends_at", ddl="ends_at TEXT")
        await connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_bans_single_active
            ON bans(chat_id, user_id)
            WHERE is_active = 1;
            """
        )
        await connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_bans_chat_user
            ON bans(chat_id, user_id);
            """
        )
        await connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_bans_active_ends_at
            ON bans(chat_id, ends_at)
            WHERE is_active = 1 AND ends_at IS NOT NULL;
            """
        )
        await connection.execute(
            """
            CREATE TABLE IF NOT EXISTS message_refs (
                chat_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                sender_user_id INTEGER,
                sender_username TEXT,
                sender_display_name TEXT,
                reply_to_message_id INTEGER,
                message_date TEXT NOT NULL,
                PRIMARY KEY(chat_id, message_id),
                FOREIGN KEY(chat_id) REFERENCES chats(chat_id) ON DELETE CASCADE,
                FOREIGN KEY(sender_user_id) REFERENCES users_cache(user_id) ON DELETE SET NULL
            );
            """
        )
        await connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_message_refs_chat_sender
            ON message_refs(chat_id, sender_user_id, message_date DESC);
            """
        )
        await connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_message_refs_chat_reply
            ON message_refs(chat_id, reply_to_message_id);
            """
        )
        await connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_message_refs_chat_username
            ON message_refs(chat_id, sender_username, message_date DESC)
            WHERE sender_username IS NOT NULL;
            """
        )
