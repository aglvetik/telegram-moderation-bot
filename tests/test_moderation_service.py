from __future__ import annotations

import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from aiogram.enums import ChatMemberStatus, ChatType, ParseMode

from config import AppConfig, BackupConfig, DatabaseConfig, MessagePolicyConfig, RetryConfig, SchedulerConfig
from database.db import Database
from database.migrations import run_migrations
from database.repositories.admin_levels_repo import AdminLevelsRepository
from database.repositories.bans_repo import BansRepository
from database.repositories.chats_repo import ChatsRepository
from database.repositories.message_refs_repo import MessageRefsRepository
from database.repositories.mutes_repo import MutesRepository
from database.repositories.punishments_repo import PunishmentsRepository
from database.repositories.users_repo import UsersRepository
from services.message_service import MessageService
from services.moderation_service import ModerationService
from services.scheduler_service import SchedulerService
from services.user_resolution_service import ResolvedUser
from utils.formatters import utc_now


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


def make_member(user_id: int, *, status: ChatMemberStatus, can_restrict_members: bool = False):
    class Member:
        pass

    member = Member()
    member.status = status
    member.user = type("UserStub", (), {"id": user_id, "username": f"user{user_id}", "first_name": f"User {user_id}", "last_name": None})()
    member.can_restrict_members = can_restrict_members
    return member


class FakeBot:
    def __init__(self, member_map: dict[int, object] | None = None) -> None:
        self.id = 999
        self.member_map = member_map or {}
        self.restrict_calls: list[dict] = []
        self.ban_calls: list[dict] = []
        self.unban_calls: list[dict] = []

    async def restrict_chat_member(self, **kwargs):
        self.restrict_calls.append(kwargs)
        return True

    async def ban_chat_member(self, **kwargs):
        self.ban_calls.append(kwargs)
        return True

    async def unban_chat_member(self, **kwargs):
        self.unban_calls.append(kwargs)
        return True

    async def get_chat_member(self, chat_id: int, user_id: int):
        return self.member_map.get(user_id)


class ModerationServiceLongDurationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="moderationbot_moderation_test_")
        database_path = Path(self.temp_dir.name) / "test.sqlite3"
        self.config = build_config(database_path)
        self.database = Database(database_path)
        await self.database.initialize()
        await run_migrations(self.database)

        self.chats_repo = ChatsRepository(self.database)
        self.admin_levels_repo = AdminLevelsRepository(self.database)
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
        self.chat_id = -1008080
        await self.chats_repo.upsert_chat(
            chat_id=self.chat_id,
            chat_type=ChatType.SUPERGROUP,
            title="Moderation chat",
            settings={},
        )
        self.moderator = ResolvedUser(user_id=700, username="mod", display_name="Moderator")
        self.target = ResolvedUser(user_id=701, username="target", display_name="Target")

    async def asyncTearDown(self) -> None:
        self.temp_dir.cleanup()

    async def test_long_mute_above_old_cap_is_saved_as_timed_mute(self) -> None:
        await self.admin_levels_repo.set_level(chat_id=self.chat_id, user_id=self.moderator.user_id, admin_level=4, granted_by_user_id=None)
        bot = FakeBot()

        result = await self.moderation_service.mute(
            bot=bot,
            chat_id=self.chat_id,
            moderator=self.moderator,
            target=self.target,
            duration_seconds=90 * 86400,
            reason="Флуд",
        )

        self.assertIsNotNone(bot.restrict_calls[-1]["until_date"])
        mute = await self.mutes_repo.get_active_mute(self.chat_id, self.target.user_id)
        self.assertIsNotNone(mute)
        self.assertIsNotNone(mute.ends_at)
        self.assertIn("90 дней", result.message)

    async def test_very_large_mute_becomes_permanent(self) -> None:
        await self.admin_levels_repo.set_level(chat_id=self.chat_id, user_id=self.moderator.user_id, admin_level=4, granted_by_user_id=None)
        bot = FakeBot()

        result = await self.moderation_service.mute(
            bot=bot,
            chat_id=self.chat_id,
            moderator=self.moderator,
            target=self.target,
            duration_seconds=400 * 86400,
            reason="Токсичность",
        )

        self.assertIsNone(bot.restrict_calls[-1]["until_date"])
        mute = await self.mutes_repo.get_active_mute(self.chat_id, self.target.user_id)
        self.assertIsNotNone(mute)
        self.assertIsNone(mute.ends_at)
        self.assertIn("бессрочно", result.message)

    async def test_very_large_ban_becomes_permanent(self) -> None:
        await self.admin_levels_repo.set_level(chat_id=self.chat_id, user_id=self.moderator.user_id, admin_level=4, granted_by_user_id=None)
        bot = FakeBot()

        await self.moderation_service.ban(
            bot=bot,
            chat_id=self.chat_id,
            moderator=self.moderator,
            target=self.target,
            duration_seconds=400 * 86400,
            reason="Спам",
        )

        self.assertNotIn("until_date", bot.ban_calls[-1])
        ban = await self.bans_repo.get_active_ban(self.chat_id, self.target.user_id)
        self.assertIsNotNone(ban)
        self.assertIsNone(ban.ends_at)

    async def test_scheduler_recovery_keeps_permanent_mute_active(self) -> None:
        now = utc_now()
        await self.mutes_repo.create_active_mute(
            chat_id=self.chat_id,
            user_id=self.target.user_id,
            started_at=now - timedelta(days=2),
            ends_at=None,
            reason="Токсичность",
            moderator_user_id=self.moderator.user_id,
        )
        bot = FakeBot(
            {
                self.target.user_id: make_member(self.target.user_id, status=ChatMemberStatus.MEMBER),
            }
        )

        await self.scheduler.recover(bot)

        mute = await self.mutes_repo.get_active_mute(self.chat_id, self.target.user_id)
        self.assertIsNotNone(mute)
        self.assertIsNone(mute.ends_at)
        self.assertTrue(bot.restrict_calls)
        self.assertIsNone(bot.restrict_calls[-1]["until_date"])

    async def test_scheduler_recovery_expires_timed_mute(self) -> None:
        expired_at = utc_now() - timedelta(minutes=5)
        await self.mutes_repo.create_active_mute(
            chat_id=self.chat_id,
            user_id=self.target.user_id,
            started_at=expired_at - timedelta(hours=1),
            ends_at=expired_at,
            reason="Флуд",
            moderator_user_id=self.moderator.user_id,
        )
        bot = FakeBot(
            {
                self.target.user_id: make_member(self.target.user_id, status=ChatMemberStatus.MEMBER),
            }
        )

        await self.scheduler.recover(bot)

        self.assertIsNone(await self.mutes_repo.get_active_mute(self.chat_id, self.target.user_id))
        self.assertTrue(bot.restrict_calls)

    async def test_service_rejects_higher_level_target(self) -> None:
        await self.admin_levels_repo.set_level(chat_id=self.chat_id, user_id=self.moderator.user_id, admin_level=2, granted_by_user_id=None)
        await self.admin_levels_repo.set_level(chat_id=self.chat_id, user_id=self.target.user_id, admin_level=3, granted_by_user_id=None)
        bot = FakeBot()

        with self.assertRaisesRegex(Exception, "таким же или более высоким уровнем"):
            await self.moderation_service.mute(
                bot=bot,
                chat_id=self.chat_id,
                moderator=self.moderator,
                target=self.target,
                duration_seconds=3600,
                reason="Флуд",
            )

    async def test_service_allows_strictly_lower_level_target(self) -> None:
        await self.admin_levels_repo.set_level(chat_id=self.chat_id, user_id=self.moderator.user_id, admin_level=4, granted_by_user_id=None)
        await self.admin_levels_repo.set_level(chat_id=self.chat_id, user_id=self.target.user_id, admin_level=3, granted_by_user_id=None)
        bot = FakeBot()

        result = await self.moderation_service.mute(
            bot=bot,
            chat_id=self.chat_id,
            moderator=self.moderator,
            target=self.target,
            duration_seconds=3600,
            reason="Флуд",
        )

        self.assertIn("лишается права слова", result.message)
        self.assertTrue(bot.restrict_calls)
