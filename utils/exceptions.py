from __future__ import annotations

from utils.constants import MessageCategory


class BotError(Exception):
    default_category = MessageCategory.TRANSIENT_ERROR

    def __init__(
        self,
        user_message: str,
        *,
        log_message: str | None = None,
        category: MessageCategory | None = None,
    ) -> None:
        super().__init__(log_message or user_message)
        self.user_message = user_message
        self.log_message = log_message or user_message
        self.category = category or self.default_category


class ParseCommandError(BotError):
    pass


class PermissionDeniedError(BotError):
    pass


class ValidationError(BotError):
    pass


class TargetResolutionError(BotError):
    pass


class TelegramActionError(BotError):
    pass


class UnsupportedChatError(BotError):
    default_category = MessageCategory.TRANSIENT_SERVICE


class DatabaseOperationError(BotError):
    pass


class AlreadyMutedError(BotError):
    default_category = MessageCategory.TRANSIENT_SERVICE
