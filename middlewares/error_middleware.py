from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import Bot
from aiogram.dispatcher.middlewares.base import BaseMiddleware
from aiogram.types import ChatMemberUpdated, Message, TelegramObject

from services import ServiceContainer
from utils.constants import MessageCategory
from utils.exceptions import BotError


class ErrorMiddleware(BaseMiddleware):
    def __init__(self) -> None:
        self.logger = logging.getLogger(__name__)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        try:
            return await handler(event, data)
        except BotError as exc:
            self.logger.warning("Handled bot error: %s", exc.log_message)
            await self._notify_user(event, data, exc.user_message, exc.category)
            return None
        except Exception:
            self.logger.exception("Unhandled bot error")
            services: ServiceContainer | None = data.get("services")
            await self._notify_user(
                event,
                data,
                services.messages.internal_error() if services is not None else "❌ <b>Произошла внутренняя ошибка.</b>\nПопробуйте повторить действие чуть позже.",
                MessageCategory.TRANSIENT_ERROR,
            )
            return None

    async def _notify_user(
        self,
        event: TelegramObject,
        data: dict[str, Any],
        text: str,
        category: MessageCategory,
    ) -> None:
        services: ServiceContainer | None = data.get("services")
        bot: Bot | None = data.get("bot")
        if isinstance(event, Message):
            if services is not None and bot is not None:
                await services.messages.reply(bot=bot, message=event, text=text, category=category)
                return
            await event.answer(text)
            return
        if isinstance(event, ChatMemberUpdated) and bot is not None:
            try:
                if services is not None:
                    await services.messages.send_to_chat(bot=bot, chat_id=event.chat.id, text=text, category=category)
                else:
                    await bot.send_message(event.chat.id, text)
            except Exception:
                self.logger.debug("Could not send error message to chat %s", event.chat.id)
