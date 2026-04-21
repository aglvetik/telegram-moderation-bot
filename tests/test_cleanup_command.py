from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from aiogram.enums import ChatMemberStatus, ChatType, ParseMode
from aiogram.exceptions import TelegramAPIError

from config import AppConfig, BackupConfig, DatabaseConfig, MessagePolicyConfig, RetryConfig, SchedulerConfig
from database.db import Database
from database.migrations import run_migrations
from database.models import ActionType
from database.repositories.admin_levels_repo import AdminLevelsRepository
from database.repositories.bans_repo import BansRepository
from database.repositories.chats_repo import ChatsRepository
from database.repositories.message_refs_repo import MessageRefsRepository
from database.repositories.mutes_repo import MutesRepository
from database.repositories.punishments_repo import PunishmentsRepository
from database.repositories.users_repo import UsersRepository
from services.message_service import MessageService
from services.moderation_service import ModerationService
from services.parser_service import CommandKind, ParserService
from services.permission_service import PermissionService
from services.user_resolution_service import ResolvedUser
from utils.exceptions import ParseCommandError


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


def make_member(user_id: int, *, status: ChatMemberStatus, can_delete_messages: bool = False):
    return SimpleNamespace(
        status=status,
        user=SimpleNamespace(id=user_id, username=f"user{user_id}", first_name=f"User {user_id}", last_name=None),
        can_delete_messages=can_delete_messages,
    )


class FakeBot:
    def __init__(self, member_map: dict[int, object] | None = None, *, fail_message_ids: set[int] | None = None) -> None:
        self.id = 999
        self.member_map = member_map or {}
        self.fail_message_ids = fail_message_ids or set()
        self.delete_calls: list[tuple[int, int]] = []

    async def get_chat_member(self, chat_id: int, user_id: int):
        return self.member_map.get(user_id)

    async def delete_message(self, *, chat_id: int, message_id: int):
        self.delete_calls.append((chat_id, message_id))
        if message_id in self.fail_message_ids:
            raise TelegramAPIError(method=None, message="delete failed")
        return True


class CleanupParserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = ParserService()

    def test_parse_cleanup_count_without_target(self) -> None:
        parsed = self.parser.parse("очистить 50", has_reply=False)
        self.assertEqual(parsed.kind, CommandKind.CLEANUP)
        self.assertEqual(parsed.cleanup_count, 50)
        self.assertFalse(parsed.cleanup_all)
        self.assertIsNone(parsed.explicit_target)

    def test_parse_cleanup_all_with_username(self) -> None:
        parsed = self.parser.parse("удалить все @User", has_reply=False)
        self.assertEqual(parsed.kind, CommandKind.CLEANUP)
        self.assertTrue(parsed.cleanup_all)
        self.assertEqual(parsed.explicit_target.username, "User")

    def test_parse_cleanup_count_with_user_id_flexible_order(self) -> None:
        parsed = self.parser.parse("очистить 123456789 50", has_reply=False)
        self.assertEqual(parsed.kind, CommandKind.CLEANUP)
        self.assertEqual(parsed.explicit_target.user_id, 123456789)
        self.assertEqual(parsed.cleanup_count, 50)

    def test_parse_cleanup_without_amount_keeps_target_for_handler_validation(self) -> None:
        parsed = self.parser.parse("удалить @User", has_reply=False)
        self.assertEqual(parsed.kind, CommandKind.CLEANUP)
        self.assertEqual(parsed.explicit_target.username, "User")
        self.assertIsNone(parsed.cleanup_count)
        self.assertFalse(parsed.cleanup_all)

    def test_parse_cleanup_rejects_too_large_count(self) -> None:
        with self.assertRaises(ParseCommandError):
            self.parser.parse("очистить 101", has_reply=False)

    def test_parse_cleanup_rejects_zero_and_negative_counts(self) -> None:
        with self.assertRaises(ParseCommandError):
            self.parser.parse("очистить 0 @User", has_reply=False)
        with self.assertRaises(ParseCommandError):
            self.parser.parse("очистить -1 @User", has_reply=False)


class CleanupPermissionAndServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="moderationbot_cleanup_test_")
        self.database_path = Path(self.temp_dir.name) / "test.sqlite3"
        self.config = build_config(self.database_path)
        self.database = Database(self.database_path)
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
        self.permission_service = PermissionService(
            database=self.database,
            admin_levels_repo=self.admin_levels_repo,
            chats_repo=self.chats_repo,
            punishments_repo=self.punishments_repo,
            users_repo=self.users_repo,
            message_service=self.message_service,
            system_owner_user_id=self.config.system_owner_user_id,
        )
        self.moderation_service = ModerationService(
            config=self.config,
            database=self.database,
            mutes_repo=self.mutes_repo,
            bans_repo=self.bans_repo,
            punishments_repo=self.punishments_repo,
            users_repo=self.users_repo,
            message_service=self.message_service,
            message_refs_repo=self.message_refs_repo,
        )
        self.chat_id = -100700
        self.moderator = ResolvedUser(user_id=10, username="mod", display_name="Moderator")
        self.target = ResolvedUser(user_id=20, username="target", display_name="Target")
        await self.chats_repo.upsert_chat(
            chat_id=self.chat_id,
            chat_type=ChatType.SUPERGROUP,
            title="Cleanup chat",
            settings={},
        )
        await self.users_repo.upsert_user(
            user_id=self.target.user_id,
            username=self.target.username,
            display_name=self.target.display_name,
            first_name=None,
            last_name=None,
            last_seen_chat_id=self.chat_id,
        )

    async def asyncTearDown(self) -> None:
        self.temp_dir.cleanup()

    async def _add_ref(self, message_id: int, sender_user_id: int | None = None) -> None:
        actual_sender_id = sender_user_id or self.target.user_id
        if actual_sender_id != self.target.user_id:
            await self.users_repo.upsert_user(
                user_id=actual_sender_id,
                username=f"user{actual_sender_id}",
                display_name=f"User {actual_sender_id}",
                first_name=None,
                last_name=None,
                last_seen_chat_id=self.chat_id,
            )
        await self.message_refs_repo.upsert_message_ref(
            chat_id=self.chat_id,
            message_id=message_id,
            sender_user_id=actual_sender_id,
            sender_username="target",
            sender_display_name="Target",
            reply_to_message_id=None,
            message_date=datetime.now(timezone.utc),
        )

    async def test_level_four_can_use_cleanup_when_bot_can_delete_messages(self) -> None:
        await self.admin_levels_repo.set_level(chat_id=self.chat_id, user_id=10, admin_level=4, granted_by_user_id=None)
        bot = FakeBot(
            {
                10: make_member(10, status=ChatMemberStatus.MEMBER),
                20: make_member(20, status=ChatMemberStatus.MEMBER),
                999: make_member(999, status=ChatMemberStatus.ADMINISTRATOR, can_delete_messages=True),
            }
        )

        result = await self.permission_service.ensure_cleanup_allowed(
            bot=bot,
            chat_id=self.chat_id,
            actor=SimpleNamespace(id=10, username="mod", first_name="Mod", last_name=None),
            target=ResolvedUser(user_id=20, username="target", display_name="Target", member=make_member(20, status=ChatMemberStatus.MEMBER)),
        )

        self.assertEqual(result, (4, 0))

    async def test_level_three_cannot_use_cleanup(self) -> None:
        await self.admin_levels_repo.set_level(chat_id=self.chat_id, user_id=11, admin_level=3, granted_by_user_id=None)
        bot = FakeBot(
            {
                11: make_member(11, status=ChatMemberStatus.MEMBER),
                20: make_member(20, status=ChatMemberStatus.MEMBER),
                999: make_member(999, status=ChatMemberStatus.ADMINISTRATOR, can_delete_messages=True),
            }
        )

        with self.assertRaises(Exception):
            await self.permission_service.ensure_cleanup_allowed(
                bot=bot,
                chat_id=self.chat_id,
                actor=SimpleNamespace(id=11, username="mod", first_name="Mod", last_name=None),
                target=ResolvedUser(user_id=20, username="target", display_name="Target", member=make_member(20, status=ChatMemberStatus.MEMBER)),
            )

    async def test_cleanup_still_requires_bot_delete_rights(self) -> None:
        await self.admin_levels_repo.set_level(chat_id=self.chat_id, user_id=12, admin_level=4, granted_by_user_id=None)
        bot = FakeBot(
            {
                12: make_member(12, status=ChatMemberStatus.MEMBER),
                20: make_member(20, status=ChatMemberStatus.MEMBER),
                999: make_member(999, status=ChatMemberStatus.ADMINISTRATOR, can_delete_messages=False),
            }
        )

        with self.assertRaises(Exception):
            await self.permission_service.ensure_cleanup_allowed(
                bot=bot,
                chat_id=self.chat_id,
                actor=SimpleNamespace(id=12, username="mod", first_name="Mod", last_name=None),
                target=ResolvedUser(user_id=20, username="target", display_name="Target", member=make_member(20, status=ChatMemberStatus.MEMBER)),
            )

    async def test_numeric_cleanup_deletes_recent_target_messages_only(self) -> None:
        await self.admin_levels_repo.set_level(chat_id=self.chat_id, user_id=self.moderator.user_id, admin_level=4, granted_by_user_id=None)
        await self._add_ref(10)
        await self._add_ref(20)
        await self._add_ref(30)
        await self._add_ref(40, sender_user_id=777)
        bot = FakeBot()

        result = await self.moderation_service.cleanup_messages(
            bot=bot,
            chat_id=self.chat_id,
            moderator=self.moderator,
            target=self.target,
            count=2,
            delete_all=False,
        )

        self.assertEqual(bot.delete_calls, [(self.chat_id, 30), (self.chat_id, 20)])
        self.assertIn("удалено: <b>2</b>", result.message)
        self.assertIsNone(await self.message_refs_repo.get_message_ref(chat_id=self.chat_id, message_id=30))
        self.assertIsNotNone(await self.message_refs_repo.get_message_ref(chat_id=self.chat_id, message_id=10))

    async def test_cleanup_reports_partial_delete_failures(self) -> None:
        await self.admin_levels_repo.set_level(chat_id=self.chat_id, user_id=self.moderator.user_id, admin_level=4, granted_by_user_id=None)
        await self._add_ref(10)
        await self._add_ref(20)
        await self._add_ref(30)
        bot = FakeBot(fail_message_ids={20})

        result = await self.moderation_service.cleanup_messages(
            bot=bot,
            chat_id=self.chat_id,
            moderator=self.moderator,
            target=self.target,
            count=2,
            delete_all=False,
        )

        self.assertIn("удалено: <b>1</b>", result.message)
        self.assertIn("не удалось удалить: <b>1</b>", result.message)
        self.assertIsNone(await self.message_refs_repo.get_message_ref(chat_id=self.chat_id, message_id=30))
        self.assertIsNotNone(await self.message_refs_repo.get_message_ref(chat_id=self.chat_id, message_id=20))

    async def test_cleanup_all_uses_available_message_refs_and_records_history(self) -> None:
        await self.admin_levels_repo.set_level(chat_id=self.chat_id, user_id=self.moderator.user_id, admin_level=4, granted_by_user_id=None)
        await self._add_ref(10)
        await self._add_ref(20)
        bot = FakeBot()

        result = await self.moderation_service.cleanup_messages(
            bot=bot,
            chat_id=self.chat_id,
            moderator=self.moderator,
            target=self.target,
            count=None,
            delete_all=True,
        )

        self.assertEqual(bot.delete_calls, [(self.chat_id, 20), (self.chat_id, 10)])
        self.assertIn("все доступные сообщения", result.message)
        history = await self.punishments_repo.list_user_history(chat_id=self.chat_id, target_user_id=self.target.user_id, limit=5)
        self.assertTrue(history)
        self.assertEqual(history[0].action_type, ActionType.CLEANUP.value)

    async def test_cleanup_reports_when_no_deletable_refs_exist(self) -> None:
        await self.admin_levels_repo.set_level(chat_id=self.chat_id, user_id=self.moderator.user_id, admin_level=4, granted_by_user_id=None)
        bot = FakeBot()

        result = await self.moderation_service.cleanup_messages(
            bot=bot,
            chat_id=self.chat_id,
            moderator=self.moderator,
            target=self.target,
            count=10,
            delete_all=False,
        )

        self.assertEqual(bot.delete_calls, [])
        self.assertIn("не найдены", result.message)


if __name__ == "__main__":
    unittest.main()
