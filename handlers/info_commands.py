from __future__ import annotations

from aiogram import Bot, Router
from aiogram.enums import ChatType
from aiogram.types import Message

from filters import PlainCommandFilter
from services import ServiceContainer
from services.parser_service import CommandKind
from utils.constants import BOT_COMMAND_ALIASES, MODERATION_REQUIRED_LEVELS, MessageCategory
from utils.exceptions import UnsupportedChatError

router = Router(name="info_commands")


@router.message(PlainCommandFilter(BOT_COMMAND_ALIASES["info"] | BOT_COMMAND_ALIASES["history"] | BOT_COMMAND_ALIASES["active_mutes"]))
async def handle_info_commands(message: Message, bot: Bot, services: ServiceContainer) -> None:
    if not message.text or not message.from_user:
        return

    if message.chat.type in {ChatType.PRIVATE, ChatType.CHANNEL}:
        raise UnsupportedChatError(
            services.messages.moderation_groups_only()
            if message.chat.type == ChatType.PRIVATE
            else services.messages.moderation_channels_only()
        )

    parsed = services.parser.parse(message.text, has_reply=message.reply_to_message is not None)
    await services.permissions.ensure_view_access(
        bot=bot,
        chat_id=message.chat.id,
        actor=message.from_user,
        required_level=MODERATION_REQUIRED_LEVELS["active_mutes" if parsed.kind == CommandKind.ACTIVE_MUTES else parsed.kind.value],
    )

    if parsed.kind == CommandKind.ACTIVE_MUTES:
        await services.messages.reply(
            bot=bot,
            message=message,
            text=await services.moderation.get_active_mutes_message(
                chat_id=message.chat.id,
                limit=services.moderation.config.active_mutes_limit,
            ),
            category=MessageCategory.INFO_OUTPUT,
        )
        return

    target = await services.users.resolve_target(bot, message, parsed)
    if parsed.kind == CommandKind.INFO:
        await services.permissions.get_level(message.chat.id, target.user_id, bot=bot, member=target.member)
        await services.messages.reply(
            bot=bot,
            message=message,
            text=await services.moderation.get_user_info_message(chat_id=message.chat.id, target=target),
            category=MessageCategory.INFO_OUTPUT,
        )
        return

    await services.messages.reply(
        bot=bot,
        message=message,
        text=await services.moderation.get_history_message(
            chat_id=message.chat.id,
            target=target,
            limit=services.moderation.config.history_limit,
        ),
        category=MessageCategory.HISTORY_OUTPUT,
    )
