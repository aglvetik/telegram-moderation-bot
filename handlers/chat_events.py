from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.types import ChatMemberUpdated, Message

from services import ServiceContainer
from utils.constants import MessageCategory

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
async def handle_chat_member_update(_: ChatMemberUpdated) -> None:
    return


@router.message(F.migrate_to_chat_id)
async def handle_chat_migration(message: Message, services: ServiceContainer) -> None:
    if message.migrate_to_chat_id:
        await services.chats.migrate_chat(message.chat.id, message.migrate_to_chat_id)
