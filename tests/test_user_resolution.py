from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from aiogram.enums import ChatType, ParseMode

from config import AppConfig, BackupConfig, DatabaseConfig, MessagePolicyConfig, RetryConfig, SchedulerConfig
from database.db import Database
from database.migrations import run_migrations
from database.repositories.chats_repo import ChatsRepository
from database.repositories.message_refs_repo import MessageRefsRepository
from database.repositories.users_repo import UsersRepository
from services.message_service import MessageService
from services.parser_service import ParserService
from services.user_resolution_service import UserResolutionService


def build_config() -> AppConfig:
    return AppConfig(
        bot_token="123456:TESTTOKEN",
        parse_mode=ParseMode.HTML,
        log_level="INFO",
        system_owner_user_id=5300889569,
        data_retention_days=90,
        history_limit=5,
        active_mutes_limit=20,
        database=DatabaseConfig(path=Path("test.sqlite3")),
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
    async def get_chat_member(self, chat_id: int, user_id: int):
        return None


class UserResolutionServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="moderationbot_user_resolution_")
        self.database = Database(Path(self.temp_dir.name) / "test.sqlite3")
        await self.database.initialize()
        await run_migrations(self.database)

        self.chats_repo = ChatsRepository(self.database)
        self.users_repo = UsersRepository(self.database)
        self.message_refs_repo = MessageRefsRepository(self.database)
        self.service = UserResolutionService(
            database=self.database,
            chats_repo=self.chats_repo,
            users_repo=self.users_repo,
            message_refs_repo=self.message_refs_repo,
            message_service=MessageService(build_config()),
        )
        self.parser = ParserService()
        self.bot = FakeBot()

    async def asyncTearDown(self) -> None:
        self.temp_dir.cleanup()

    async def test_username_lookup_is_normalized_and_updates(self) -> None:
        await self.users_repo.upsert_user(
            user_id=100,
            username="@TestUser",
            display_name="Test User",
            first_name="Test",
            last_name="User",
            last_seen_chat_id=-1001,
        )
        cached = await self.users_repo.get_by_username("testuser")
        self.assertIsNotNone(cached)
        self.assertEqual(cached.user_id, 100)
        self.assertEqual(cached.username, "testuser")

        await self.users_repo.upsert_user(
            user_id=100,
            username="NewName",
            display_name="Test User",
            first_name="Test",
            last_name="User",
            last_seen_chat_id=-1001,
        )

        self.assertIsNone(await self.users_repo.get_by_username("testuser"))
        updated = await self.users_repo.get_by_username("@newname")
        self.assertIsNotNone(updated)
        self.assertEqual(updated.user_id, 100)

    async def test_cached_username_resolution_works(self) -> None:
        await self.chats_repo.upsert_chat(chat_id=-1001, chat_type=ChatType.SUPERGROUP, title="Chat", settings={})
        await self.users_repo.upsert_user(
            user_id=200,
            username="KnownUser",
            display_name="Known User",
            first_name="Known",
            last_name="User",
            last_seen_chat_id=-1001,
        )
        message = SimpleNamespace(chat=SimpleNamespace(id=-1001), reply_to_message=None)
        parsed = self.parser.parse("мут @knownuser 30м", has_reply=False)
        resolved = await self.service.resolve_target(self.bot, message, parsed)
        self.assertEqual(resolved.user_id, 200)
        self.assertEqual(resolved.username, "knownuser")

    async def test_uncached_username_fails_honestly(self) -> None:
        await self.chats_repo.upsert_chat(chat_id=-1001, chat_type=ChatType.SUPERGROUP, title="Chat", settings={})
        message = SimpleNamespace(chat=SimpleNamespace(id=-1001), reply_to_message=None)
        parsed = self.parser.parse("мут @missinguser 30м", has_reply=False)
        with self.assertRaises(Exception):
            await self.service.resolve_target(self.bot, message, parsed)

    async def test_reply_resolution_uses_message_ref_cache_when_reply_payload_missing(self) -> None:
        await self.chats_repo.upsert_chat(chat_id=-1001, chat_type=ChatType.SUPERGROUP, title="Chat", settings={})
        await self.users_repo.upsert_user(
            user_id=555,
            username="ReplyUser",
            display_name="Reply User",
            first_name="Reply",
            last_name="User",
            last_seen_chat_id=-1001,
        )
        await self.message_refs_repo.upsert_message_ref(
            chat_id=-1001,
            message_id=77,
            sender_user_id=555,
            sender_username="ReplyUser",
            sender_display_name="Reply User",
            reply_to_message_id=None,
            message_date=datetime.now(timezone.utc),
        )

        message = SimpleNamespace(
            chat=SimpleNamespace(id=-1001),
            reply_to_message=SimpleNamespace(message_id=77, from_user=None),
        )
        parsed = self.parser.parse("мут", has_reply=True)
        resolved = await self.service.resolve_target(self.bot, message, parsed)
        self.assertEqual(resolved.user_id, 555)
        self.assertEqual(resolved.username, "replyuser")

    async def test_reply_plus_same_explicit_username_is_allowed(self) -> None:
        await self.chats_repo.upsert_chat(chat_id=-1001, chat_type=ChatType.SUPERGROUP, title="Chat", settings={})
        await self.users_repo.upsert_user(
            user_id=777,
            username="SameUser",
            display_name="Same User",
            first_name="Same",
            last_name="User",
            last_seen_chat_id=-1001,
        )
        message = SimpleNamespace(
            chat=SimpleNamespace(id=-1001),
            reply_to_message=SimpleNamespace(
                message_id=80,
                from_user=SimpleNamespace(id=777, username="SameUser", first_name="Same", last_name="User"),
            ),
        )
        parsed = self.parser.parse("мут @sameuser 30 минут", has_reply=True)
        resolved = await self.service.resolve_target(self.bot, message, parsed)
        self.assertEqual(resolved.user_id, 777)

    async def test_reply_plus_same_explicit_user_id_is_allowed(self) -> None:
        await self.chats_repo.upsert_chat(chat_id=-1001, chat_type=ChatType.SUPERGROUP, title="Chat", settings={})
        message = SimpleNamespace(
            chat=SimpleNamespace(id=-1001),
            reply_to_message=SimpleNamespace(
                message_id=81,
                from_user=SimpleNamespace(id=778, username="SameId", first_name="Same", last_name="Id"),
            ),
        )
        parsed = self.parser.parse("бан 778 1 день", has_reply=True)
        resolved = await self.service.resolve_target(self.bot, message, parsed)
        self.assertEqual(resolved.user_id, 778)

    async def test_reply_plus_conflicting_explicit_target_fails_safely(self) -> None:
        await self.chats_repo.upsert_chat(chat_id=-1001, chat_type=ChatType.SUPERGROUP, title="Chat", settings={})
        await self.users_repo.upsert_user(
            user_id=900,
            username="AnotherUser",
            display_name="Another User",
            first_name="Another",
            last_name="User",
            last_seen_chat_id=-1001,
        )
        message = SimpleNamespace(
            chat=SimpleNamespace(id=-1001),
            reply_to_message=SimpleNamespace(
                message_id=82,
                from_user=SimpleNamespace(id=779, username="ReplyUser", first_name="Reply", last_name="User"),
            ),
        )
        parsed = self.parser.parse("мут @anotheruser 30 минут", has_reply=True)
        with self.assertRaises(Exception):
            await self.service.resolve_target(self.bot, message, parsed)


if __name__ == "__main__":
    unittest.main()
