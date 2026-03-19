from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.filters import CommandStart
from aiogram.types import Message

from filters import PlainCommandFilter
from services import ServiceContainer
from utils.constants import BOT_COMMAND_ALIASES, MessageCategory

router = Router(name="help_commands")


@router.message(CommandStart(), F.chat.type == ChatType.PRIVATE)
async def handle_private_start(message: Message, bot: Bot, services: ServiceContainer) -> None:
    await services.messages.reply(
        bot=bot,
        message=message,
        text=services.messages.private_start(),
        category=MessageCategory.HELP_OUTPUT,
    )


@router.message(PlainCommandFilter(BOT_COMMAND_ALIASES["help"]))
async def handle_help(message: Message, bot: Bot, services: ServiceContainer) -> None:
    if not message.text:
        return

    if message.chat.type == ChatType.PRIVATE or not message.from_user:
        await services.messages.reply(
            bot=bot,
            message=message,
            text=services.messages.help_message(0, private_chat=True),
            category=MessageCategory.HELP_OUTPUT,
        )
        return

    level = await services.permissions.get_my_effective_level(message.chat.id, message.from_user)
    if level < 1:
        await services.messages.reply(
            bot=bot,
            message=message,
            text=services.messages.help_unavailable_for_level_zero(),
            category=MessageCategory.HELP_OUTPUT,
        )
        return

    await services.messages.reply(
        bot=bot,
        message=message,
        text=services.messages.help_message(level),
        category=MessageCategory.HELP_OUTPUT,
    )
