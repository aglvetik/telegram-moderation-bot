from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiogram.enums import ChatType

from handlers.help_commands import handle_private_start
from utils.constants import MessageCategory


class HelpCommandHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_private_start_handler_uses_private_start_message(self) -> None:
        reply_mock = AsyncMock()
        services = SimpleNamespace(
            messages=SimpleNamespace(
                private_start=lambda: "PRIVATE_START_TEXT",
                reply=reply_mock,
            )
        )
        message = SimpleNamespace(
            text="/start",
            chat=SimpleNamespace(type=ChatType.PRIVATE),
            from_user=SimpleNamespace(id=1),
        )

        await handle_private_start(message, object(), services)

        reply_mock.assert_awaited_once()
        self.assertEqual(reply_mock.await_args.kwargs["text"], "PRIVATE_START_TEXT")
        self.assertEqual(reply_mock.await_args.kwargs["category"], MessageCategory.HELP_OUTPUT)


if __name__ == "__main__":
    unittest.main()
