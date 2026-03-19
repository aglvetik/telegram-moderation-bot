from __future__ import annotations

from aiogram import Bot, Router
from aiogram.enums import ChatType
from aiogram.types import Message

from filters import PlainCommandFilter
from services import ServiceContainer
from services.parser_service import CommandKind
from utils.constants import BOT_COMMAND_ALIASES
from utils.exceptions import UnsupportedChatError

router = Router(name="moderation")


@router.message(
    PlainCommandFilter(
        BOT_COMMAND_ALIASES["mute"]
        | BOT_COMMAND_ALIASES["unmute"]
        | BOT_COMMAND_ALIASES["kick"]
        | BOT_COMMAND_ALIASES["ban"]
        | BOT_COMMAND_ALIASES["unban"]
    )
)
async def handle_moderation_command(message: Message, bot: Bot, services: ServiceContainer) -> None:
    if not message.text or not message.from_user:
        return

    if message.chat.type == ChatType.PRIVATE:
        raise UnsupportedChatError(services.messages.moderation_groups_only())
    if message.chat.type == ChatType.CHANNEL:
        raise UnsupportedChatError(services.messages.moderation_channels_only())

    parsed = services.parser.parse(message.text, has_reply=message.reply_to_message is not None)
    moderator = services.users.build_actor(message.from_user)
    target = await services.users.resolve_target(bot, message, parsed)

    await services.permissions.ensure_moderation_allowed(
        bot=bot,
        chat_id=message.chat.id,
        actor=message.from_user,
        target=target,
        action=parsed.kind.value,
    )

    if parsed.kind == CommandKind.MUTE:
        result = await services.moderation.mute(
            bot=bot,
            chat_id=message.chat.id,
            moderator=moderator,
            target=target,
            duration_seconds=parsed.duration_seconds or 0,
            reason=parsed.reason,
        )
    elif parsed.kind == CommandKind.UNMUTE:
        result = await services.moderation.unmute(
            bot=bot,
            chat_id=message.chat.id,
            moderator=moderator,
            target=target,
        )
    elif parsed.kind == CommandKind.KICK:
        result = await services.moderation.kick(
            bot=bot,
            chat_id=message.chat.id,
            moderator=moderator,
            target=target,
            reason=parsed.reason,
        )
    elif parsed.kind == CommandKind.BAN:
        result = await services.moderation.ban(
            bot=bot,
            chat_id=message.chat.id,
            moderator=moderator,
            target=target,
            duration_seconds=parsed.duration_seconds,
            reason=parsed.reason,
        )
    else:
        result = await services.moderation.unban(
            bot=bot,
            chat_id=message.chat.id,
            moderator=moderator,
            target=target,
        )

    await services.messages.reply(
        bot=bot,
        message=message,
        text=result.message,
        category=result.category,
    )
    if result.delete_command:
        await services.messages.maybe_delete_command(bot=bot, message=message)
