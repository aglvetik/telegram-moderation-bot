from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from aiogram.enums import ChatType

from database.db import Database
from database.migrations import run_migrations
from database.repositories.chats_repo import ChatsRepository
from database.repositories.message_refs_repo import MessageRefsRepository
from database.repositories.users_repo import UsersRepository


class MessageRefsRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="moderationbot_message_refs_")
        self.database = Database(Path(self.temp_dir.name) / "test.sqlite3")
        await self.database.initialize()
        await run_migrations(self.database)

        self.chats_repo = ChatsRepository(self.database)
        self.users_repo = UsersRepository(self.database)
        self.message_refs_repo = MessageRefsRepository(self.database)

        await self.chats_repo.upsert_chat(chat_id=-2001, chat_type=ChatType.SUPERGROUP, title="Chat", settings={})
        await self.users_repo.upsert_user(
            user_id=321,
            username="RefUser",
            display_name="Ref User",
            first_name="Ref",
            last_name="User",
            last_seen_chat_id=-2001,
        )

    async def asyncTearDown(self) -> None:
        self.temp_dir.cleanup()

    async def test_store_minimal_message_metadata(self) -> None:
        await self.message_refs_repo.upsert_message_ref(
            chat_id=-2001,
            message_id=900,
            sender_user_id=321,
            sender_username="RefUser",
            sender_display_name="Ref User",
            reply_to_message_id=899,
            message_date=datetime.now(timezone.utc),
        )

        record = await self.message_refs_repo.get_message_ref(chat_id=-2001, message_id=900)
        self.assertIsNotNone(record)
        self.assertEqual(record.chat_id, -2001)
        self.assertEqual(record.message_id, 900)
        self.assertEqual(record.sender_user_id, 321)
        self.assertEqual(record.sender_username, "refuser")
        self.assertEqual(record.reply_to_message_id, 899)

        row = await self.database.fetchone("SELECT * FROM message_refs WHERE chat_id = ? AND message_id = ?;", (-2001, 900))
        self.assertEqual(
            set(row.keys()),
            {
                "chat_id",
                "message_id",
                "sender_user_id",
                "sender_username",
                "sender_display_name",
                "reply_to_message_id",
                "message_date",
            },
        )


if __name__ == "__main__":
    unittest.main()
