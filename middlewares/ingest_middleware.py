from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram.dispatcher.middlewares.base import BaseMiddleware
from aiogram.types import ChatMemberUpdated, Message, TelegramObject

from services import ServiceContainer


class IngestMiddleware(BaseMiddleware):
    def __init__(self) -> None:
        self.logger = logging.getLogger(__name__)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        services: ServiceContainer | None = data.get("services")
        if services is not None:
            try:
                if isinstance(event, Message):
                    await services.users.ingest_message(event)
                elif isinstance(event, ChatMemberUpdated):
                    await services.users.ingest_chat_member_update(event)
            except Exception:
                self.logger.exception("Failed to ingest update payload")
        return await handler(event, data)
