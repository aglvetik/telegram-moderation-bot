from __future__ import annotations

from dataclasses import dataclass

from services.chat_service import ChatService
from services.message_service import MessageService
from services.moderation_service import ModerationService
from services.parser_service import ParserService
from services.permission_service import PermissionService
from services.scheduler_service import SchedulerService
from services.user_resolution_service import UserResolutionService


@dataclass(slots=True)
class ServiceContainer:
    chats: ChatService
    messages: MessageService
    moderation: ModerationService
    parser: ParserService
    permissions: PermissionService
    scheduler: SchedulerService
    users: UserResolutionService


__all__ = [
    "ChatService",
    "MessageService",
    "ModerationService",
    "ParserService",
    "PermissionService",
    "SchedulerService",
    "ServiceContainer",
    "UserResolutionService",
]
