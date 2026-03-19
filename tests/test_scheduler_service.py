from __future__ import annotations

import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from aiogram.enums import ChatType, ParseMode

from config import AppConfig, BackupConfig, DatabaseConfig, MessagePolicyConfig, RetryConfig, SchedulerConfig
from database.db import Database
from database.migrations import run_migrations
from database.repositories.bans_repo import BansRepository
from database.repositories.message_refs_repo import MessageRefsRepository
from database.repositories.mutes_repo import MutesRepository
from database.repositories.punishments_repo import PunishmentsRepository
from database.repositories.users_repo import UsersRepository
from database.repositories.chats_repo import ChatsRepository
from services.message_service import MessageService
from services.moderation_service import ModerationService
from services.scheduler_service import SchedulerService
from utils.formatters import to_iso, utc_now


def build_config(database_path: Path) -> AppConfig:
    return AppConfig(
        bot_token="123456:TESTTOKEN",
        parse_mode=ParseMode.HTML,
        log_level="INFO",
        system_owner_user_id=5300889569,
        data_retention_days=90,
        history_limit=5,
        active_mutes_limit=20,
        database=DatabaseConfig(path=database_path),
        scheduler=SchedulerConfig(
            expired_mute_check_seconds=60,
            expired_ban_check_seconds=60,
            mute_verification_interval_seconds=300,
            cleanup_interval_seconds=86400,
            sqlite_backup_interval_seconds=21600,
        ),
        backup=BackupConfig(enabled=False, directory=Path("backups")),
        retry=RetryConfig(retries=0, base_delay_seconds=0.1),
        message_policy=MessagePolicyConfig(
            delete_command_messages=False,
            command_delete_delay_seconds=3,
            ordinary_message_delete_seconds=60,
        ),
    )


class FakeBot:
    def __init__(self) -> None:
        self.unban_calls: list[tuple[int, int]] = []

    async def unban_chat_member(self, *, chat_id: int, user_id: int, only_if_banned: bool = True):
        self.unban_calls.append((chat_id, user_id))
        return True


class SchedulerTimedBanTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="moderationbot_scheduler_test_")
        database_path = Path(self.temp_dir.name) / "test.sqlite3"
        self.config = build_config(database_path)
        self.database = Database(database_path)
        await self.database.initialize()
        await run_migrations(self.database)

        self.chats_repo = ChatsRepository(self.database)
        self.users_repo = UsersRepository(self.database)
        self.message_refs_repo = MessageRefsRepository(self.database)
        self.mutes_repo = MutesRepository(self.database)
        self.bans_repo = BansRepository(self.database)
        self.punishments_repo = PunishmentsRepository(self.database)
        self.message_service = MessageService(self.config)
        self.moderation_service = ModerationService(
            config=self.config,
            database=self.database,
            mutes_repo=self.mutes_repo,
            bans_repo=self.bans_repo,
            punishments_repo=self.punishments_repo,
            users_repo=self.users_repo,
            message_service=self.message_service,
        )
        self.scheduler = SchedulerService(
            config=self.config,
            database=self.database,
            moderation_service=self.moderation_service,
            mutes_repo=self.mutes_repo,
            bans_repo=self.bans_repo,
            punishments_repo=self.punishments_repo,
            message_refs_repo=self.message_refs_repo,
        )
        self.chat_id = -100700
        await self.chats_repo.upsert_chat(
            chat_id=self.chat_id,
            chat_type=ChatType.SUPERGROUP,
            title="Scheduler chat",
            settings={},
        )

    async def asyncTearDown(self) -> None:
        self.temp_dir.cleanup()

    async def test_timed_ban_expires_and_auto_unbans_on_recovery(self) -> None:
        expired_at = utc_now() - timedelta(minutes=5)
        banned_at = expired_at - timedelta(minutes=10)
        async with self.database.transaction() as connection:
            await self.bans_repo.create_active_ban(
                chat_id=self.chat_id,
                user_id=555,
                banned_at=banned_at,
                ends_at=expired_at,
                reason="Спам",
                moderator_user_id=777,
                connection=connection,
            )
            await self.punishments_repo.add_entry(
                chat_id=self.chat_id,
                target_user_id=555,
                target_username="user555",
                target_display_name="User 555",
                moderator_user_id=777,
                moderator_username="mod777",
                moderator_display_name="Mod 777",
                action_type="ban",
                reason="Спам",
                duration_seconds=600,
                mute_until=to_iso(expired_at),
                is_active=True,
                extra_data_json=None,
                connection=connection,
            )

        bot = FakeBot()
        await self.scheduler.recover(bot)

        self.assertEqual(bot.unban_calls, [(self.chat_id, 555)])
        self.assertIsNone(await self.bans_repo.get_active_ban(self.chat_id, 555))
        row = await self.database.fetchone(
            """
            SELECT is_active FROM punishments_history
            WHERE chat_id = ? AND target_user_id = ? AND action_type = 'ban'
            ORDER BY id DESC
            LIMIT 1;
            """,
            (self.chat_id, 555),
        )
        self.assertEqual(row["is_active"], 0)

    async def test_permanent_ban_remains_active_during_recovery(self) -> None:
        banned_at = utc_now() - timedelta(days=1)
        await self.bans_repo.create_active_ban(
            chat_id=self.chat_id,
            user_id=556,
            banned_at=banned_at,
            ends_at=None,
            reason="Токсичность",
            moderator_user_id=777,
        )

        bot = FakeBot()
        await self.scheduler.recover(bot)

        self.assertEqual(bot.unban_calls, [])
        self.assertIsNotNone(await self.bans_repo.get_active_ban(self.chat_id, 556))


if __name__ == "__main__":
    unittest.main()
