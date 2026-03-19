from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.types import ChatMemberUpdated, Message

from services import ServiceContainer
from utils.constants import MessageCategory
from utils.telegram_helpers import build_user_display_name

router = Router(name="chat_events")

_ACTIVE_STATUSES = {ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR}
_INACTIVE_STATUSES = {ChatMemberStatus.LEFT, ChatMemberStatus.KICKED}


@router.my_chat_member()
async def handle_bot_membership_update(event: ChatMemberUpdated, bot: Bot, services: ServiceContainer) -> None:
    old_status = event.old_chat_member.status
    new_status = event.new_chat_member.status

    if old_status not in _ACTIVE_STATUSES and new_status in _ACTIVE_STATUSES:
        await services.chats.register_chat(
            bot,
            chat_id=event.chat.id,
            chat_type=event.chat.type,
            title=event.chat.title,
        )
        if event.chat.type in {ChatType.GROUP, ChatType.SUPERGROUP}:
            await services.messages.send_to_chat(
                bot=bot,
                chat_id=event.chat.id,
                text=services.messages.welcome_group(),
                category=MessageCategory.INFO_OUTPUT,
            )
        elif event.chat.type == ChatType.CHANNEL:
            await services.messages.send_to_chat(
                bot=bot,
                chat_id=event.chat.id,
                text=services.messages.welcome_channel(),
                category=MessageCategory.INFO_OUTPUT,
            )
        return

    if old_status in _ACTIVE_STATUSES and new_status in _INACTIVE_STATUSES:
        await services.chats.deactivate_chat(event.chat.id)


@router.chat_member()
async def handle_chat_member_update(event: ChatMemberUpdated, services: ServiceContainer) -> None:
    if event.chat.type not in {ChatType.GROUP, ChatType.SUPERGROUP}:
        return

    user = getattr(event.new_chat_member, "user", None)
    if user is None:
        return

    await services.chats.sync_member_role(
        chat_id=event.chat.id,
        chat_type=event.chat.type,
        title=event.chat.title,
        user_id=user.id,
        username=user.username,
        display_name=build_user_display_name(user),
        first_name=user.first_name,
        last_name=user.last_name,
        status=event.new_chat_member.status,
    )


@router.message(F.migrate_to_chat_id)
async def handle_chat_migration(message: Message, services: ServiceContainer) -> None:
    if message.migrate_to_chat_id:
        await services.chats.migrate_chat(message.chat.id, message.migrate_to_chat_id)
