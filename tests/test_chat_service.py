from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from aiogram.enums import ChatMemberStatus, ChatType

from config import RetryConfig
from database.db import Database
from database.migrations import run_migrations
from database.repositories.admin_levels_repo import AdminLevelsRepository
from database.repositories.bans_repo import BansRepository
from database.repositories.chats_repo import ChatsRepository
from database.repositories.message_refs_repo import MessageRefsRepository
from database.repositories.mutes_repo import MutesRepository
from database.repositories.punishments_repo import PunishmentsRepository
from database.repositories.users_repo import UsersRepository
from services.chat_service import ChatService


class FakeBot:
    async def get_chat_administrators(self, chat_id: int):
        owner = SimpleNamespace(id=111, username="owner_user", first_name="Chat", last_name="Owner")
        admin = SimpleNamespace(id=222, username="admin_user", first_name="Alice", last_name="Admin")
        return [
            SimpleNamespace(status=ChatMemberStatus.CREATOR, user=owner),
            SimpleNamespace(status=ChatMemberStatus.ADMINISTRATOR, user=admin),
        ]


class ChatServiceJoinFlowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="moderationbot_chat_test_")
        self.database = Database(Path(self.temp_dir.name) / "test.sqlite3")
        await self.database.initialize()
        await run_migrations(self.database)

        self.chats_repo = ChatsRepository(self.database)
        self.admin_levels_repo = AdminLevelsRepository(self.database)
        self.users_repo = UsersRepository(self.database)
        self.message_refs_repo = MessageRefsRepository(self.database)

    async def asyncTearDown(self) -> None:
        self.temp_dir.cleanup()

    def _build_service(self, *, system_owner_user_id: int | None) -> ChatService:
        return ChatService(
            database=self.database,
            chats_repo=self.chats_repo,
            admin_levels_repo=self.admin_levels_repo,
            punishments_repo=PunishmentsRepository(self.database),
            mutes_repo=MutesRepository(self.database),
            bans_repo=BansRepository(self.database),
            users_repo=self.users_repo,
            message_refs_repo=self.message_refs_repo,
            retry_config=RetryConfig(retries=0, base_delay_seconds=0.1),
            system_owner_user_id=system_owner_user_id,
        )

    async def test_register_chat_assigns_owner_level_five_and_admin_level_one(self) -> None:
        chat_service = self._build_service(system_owner_user_id=None)

        owner_user_id = await chat_service.register_chat(
            FakeBot(),
            chat_id=-1001234567890,
            chat_type=ChatType.SUPERGROUP,
            title="Verification chat",
        )

        self.assertEqual(owner_user_id, 111)
        chat = await self.chats_repo.get_chat(-1001234567890)
        self.assertIsNotNone(chat)
        self.assertEqual(chat.owner_user_id, 111)
        owner_level = await self.admin_levels_repo.get_level(-1001234567890, 111)
        admin_level = await self.admin_levels_repo.get_level(-1001234567890, 222)
        self.assertEqual(owner_level, 5)
        self.assertEqual(admin_level, 1)

    async def test_register_chat_preserves_level_five_for_system_owner(self) -> None:
        chat_service = self._build_service(system_owner_user_id=111)

        await chat_service.register_chat(
            FakeBot(),
            chat_id=-1001234567890,
            chat_type=ChatType.SUPERGROUP,
            title="Verification chat",
        )

        owner_level = await self.admin_levels_repo.get_level(-1001234567890, 111)
        self.assertEqual(owner_level, 5)

    async def test_sync_member_role_persists_chat_owner_level_five(self) -> None:
        chat_service = self._build_service(system_owner_user_id=None)

        await chat_service.sync_member_role(
            chat_id=-1001234567890,
            chat_type=ChatType.SUPERGROUP,
            title="Verification chat",
            user_id=333,
            username="creator_user",
            display_name="Chat Creator",
            first_name="Chat",
            last_name="Creator",
            status=ChatMemberStatus.CREATOR,
        )

        chat = await self.chats_repo.get_chat(-1001234567890)
        self.assertIsNotNone(chat)
        self.assertEqual(chat.owner_user_id, 333)
        self.assertEqual(await self.admin_levels_repo.get_level(-1001234567890, 333), 5)

    async def test_ensure_owner_snapshot_repairs_existing_chat_without_owner(self) -> None:
        chat_service = self._build_service(system_owner_user_id=None)
        await self.chats_repo.upsert_chat(
            chat_id=-1001234567890,
            chat_type=ChatType.SUPERGROUP,
            title="Existing chat",
            owner_user_id=None,
            settings={},
        )

        owner_user_id = await chat_service.ensure_owner_snapshot(FakeBot(), chat_id=-1001234567890)

        self.assertEqual(owner_user_id, 111)
        chat = await self.chats_repo.get_chat(-1001234567890)
        self.assertIsNotNone(chat)
        self.assertEqual(chat.owner_user_id, 111)
        self.assertEqual(await self.admin_levels_repo.get_level(-1001234567890, 111), 5)


if __name__ == "__main__":
    unittest.main()
