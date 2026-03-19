from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiogram.enums import ChatMemberStatus, ChatType

from handlers.admin_levels import handle_admin_levels
from services.parser_service import CommandKind
from services.user_resolution_service import ResolvedUser


def make_member(user_id: int, *, status: ChatMemberStatus):
    return SimpleNamespace(
        status=status,
        user=SimpleNamespace(id=user_id, username=f"user{user_id}", first_name=f"User {user_id}", last_name=None),
    )


class AdminLevelsHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_my_level_handler_uses_bot_backed_public_level_lookup(self) -> None:
        reply_mock = AsyncMock()
        get_my_level_mock = AsyncMock(return_value=5)
        services = SimpleNamespace(
            parser=SimpleNamespace(parse=lambda text, has_reply: SimpleNamespace(kind=CommandKind.MY_LEVEL)),
            permissions=SimpleNamespace(get_my_level=get_my_level_mock),
            messages=SimpleNamespace(
                my_level=lambda level: f"LEVEL_{level}",
                reply=reply_mock,
            ),
        )
        bot = object()
        user = SimpleNamespace(id=101)
        message = SimpleNamespace(
            text="мойуровень",
            chat=SimpleNamespace(type=ChatType.SUPERGROUP, id=-1001),
            from_user=user,
            reply_to_message=None,
        )

        await handle_admin_levels(message, bot, services)

        get_my_level_mock.assert_awaited_once_with(message.chat.id, user, bot=bot)
        self.assertEqual(reply_mock.await_args.kwargs["text"], "LEVEL_5")

    async def test_view_level_handler_passes_target_member_for_owner_refresh(self) -> None:
        reply_mock = AsyncMock()
        ensure_view_access_mock = AsyncMock()
        get_level_mock = AsyncMock(return_value=5)
        owner_member = make_member(202, status=ChatMemberStatus.CREATOR)
        target = ResolvedUser(user_id=202, username="owner", display_name="Owner", member=owner_member)
        services = SimpleNamespace(
            parser=SimpleNamespace(parse=lambda text, has_reply: SimpleNamespace(kind=CommandKind.VIEW_LEVEL)),
            permissions=SimpleNamespace(
                ensure_view_access=ensure_view_access_mock,
                get_level=get_level_mock,
            ),
            users=SimpleNamespace(resolve_target=AsyncMock(return_value=target)),
            messages=SimpleNamespace(
                level_info=lambda resolved_target, level: f"TARGET_{resolved_target.user_id}_LEVEL_{level}",
                reply=reply_mock,
            ),
        )
        bot = object()
        actor = SimpleNamespace(id=303)
        message = SimpleNamespace(
            text="уровень @owner",
            chat=SimpleNamespace(type=ChatType.SUPERGROUP, id=-1001),
            from_user=actor,
            reply_to_message=None,
        )

        await handle_admin_levels(message, bot, services)

        ensure_view_access_mock.assert_awaited_once()
        get_level_mock.assert_awaited_once_with(message.chat.id, target.user_id, bot=bot, member=owner_member)
        self.assertEqual(reply_mock.await_args.kwargs["text"], "TARGET_202_LEVEL_5")


if __name__ == "__main__":
    unittest.main()
