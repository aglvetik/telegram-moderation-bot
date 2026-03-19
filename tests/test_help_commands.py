from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiogram.enums import ChatType

from handlers.help_commands import handle_help, handle_private_start
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

    async def test_group_help_is_hidden_for_level_zero(self) -> None:
        reply_mock = AsyncMock()
        services = SimpleNamespace(
            messages=SimpleNamespace(
                help_message=lambda level, private_chat=False: f"HELP_{level}_{private_chat}",
                help_unavailable_for_level_zero=lambda: "LEVEL_ZERO_HELP",
                reply=reply_mock,
            ),
            permissions=SimpleNamespace(
                get_my_level=AsyncMock(return_value=0),
            ),
        )
        message = SimpleNamespace(
            text="помощь",
            chat=SimpleNamespace(type=ChatType.SUPERGROUP, id=-1001),
            from_user=SimpleNamespace(id=1),
        )

        await handle_help(message, object(), services)

        self.assertEqual(reply_mock.await_args.kwargs["text"], "LEVEL_ZERO_HELP")

    async def test_group_help_is_shown_for_level_one(self) -> None:
        reply_mock = AsyncMock()
        services = SimpleNamespace(
            messages=SimpleNamespace(
                help_message=lambda level, private_chat=False: f"HELP_{level}_{private_chat}",
                help_unavailable_for_level_zero=lambda: "LEVEL_ZERO_HELP",
                reply=reply_mock,
            ),
            permissions=SimpleNamespace(
                get_my_level=AsyncMock(return_value=1),
            ),
        )
        message = SimpleNamespace(
            text="помощь",
            chat=SimpleNamespace(type=ChatType.SUPERGROUP, id=-1001),
            from_user=SimpleNamespace(id=1),
        )

        await handle_help(message, object(), services)

        self.assertEqual(reply_mock.await_args.kwargs["text"], "HELP_1_False")


if __name__ == "__main__":
    unittest.main()
