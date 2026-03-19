from __future__ import annotations

from aiogram import Bot, Router
from aiogram.enums import ChatType
from aiogram.types import Message

from filters import PlainCommandFilter
from services import ServiceContainer
from services.parser_service import CommandKind
from utils.constants import BOT_COMMAND_ALIASES, MODERATION_REQUIRED_LEVELS, MessageCategory
from utils.exceptions import UnsupportedChatError

router = Router(name="admin_levels")


@router.message(
    PlainCommandFilter(
        BOT_COMMAND_ALIASES["level"]
        | BOT_COMMAND_ALIASES["raise_level"]
        | BOT_COMMAND_ALIASES["lower_level"]
        | BOT_COMMAND_ALIASES["remove_level"]
        | BOT_COMMAND_ALIASES["my_level"]
        | BOT_COMMAND_ALIASES["moderators"]
    )
)
async def handle_admin_levels(message: Message, bot: Bot, services: ServiceContainer) -> None:
    if not message.text or not message.from_user:
        return

    if message.chat.type in {ChatType.PRIVATE, ChatType.CHANNEL}:
        raise UnsupportedChatError(
            services.messages.moderation_groups_only()
            if message.chat.type == ChatType.PRIVATE
            else services.messages.moderation_channels_only()
        )

    parsed = services.parser.parse(message.text, has_reply=message.reply_to_message is not None)

    if parsed.kind == CommandKind.MY_LEVEL:
        level = await services.permissions.get_my_level(message.chat.id, message.from_user, bot=bot)
        await services.messages.reply(
            bot=bot,
            message=message,
            text=services.messages.my_level(level),
            category=MessageCategory.INFO_OUTPUT,
        )
        return

    if parsed.kind == CommandKind.MODERATORS:
        moderators = await services.permissions.list_moderators(bot=bot, chat_id=message.chat.id, actor=message.from_user)
        await services.messages.reply(
            bot=bot,
            message=message,
            text=services.messages.moderators_list(moderators),
            category=MessageCategory.INFO_OUTPUT,
        )
        return

    target = await services.users.resolve_target(bot, message, parsed)

    if parsed.kind == CommandKind.VIEW_LEVEL:
        await services.permissions.ensure_view_access(
            bot=bot,
            chat_id=message.chat.id,
            actor=message.from_user,
            required_level=MODERATION_REQUIRED_LEVELS["view_level"],
        )
        level = await services.permissions.get_level(message.chat.id, target.user_id, bot=bot, member=target.member)
        await services.messages.reply(
            bot=bot,
            message=message,
            text=services.messages.level_info(target, level),
            category=MessageCategory.INFO_OUTPUT,
        )
        return

    if parsed.kind in {CommandKind.SET_LEVEL, CommandKind.RAISE_LEVEL, CommandKind.LOWER_LEVEL}:
        level = await services.permissions.mutate_level(
            bot=bot,
            chat_id=message.chat.id,
            actor=message.from_user,
            target=target,
            requested_level=parsed.level,
            requested_delta=parsed.level_delta,
        )
        await services.messages.reply(
            bot=bot,
            message=message,
            text=services.messages.level_assigned(target, level),
            category=MessageCategory.MODERATION_RESULT,
        )
        await services.messages.maybe_delete_command(bot=bot, message=message)
        return

    await services.permissions.remove_level(
        bot=bot,
        chat_id=message.chat.id,
        actor=message.from_user,
        target=target,
    )
    await services.messages.reply(
        bot=bot,
        message=message,
        text=services.messages.level_removed(target),
        category=MessageCategory.MODERATION_RESULT,
    )
    await services.messages.maybe_delete_command(bot=bot, message=message)
