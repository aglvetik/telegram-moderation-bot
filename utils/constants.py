from __future__ import annotations

from enum import StrEnum

from aiogram.enums import ChatType


class MessageCategory(StrEnum):
    TRANSIENT_ERROR = "transient_error"
    TRANSIENT_SERVICE = "transient_service"
    MODERATION_RESULT = "moderation_result"
    INFO_OUTPUT = "info_output"
    HISTORY_OUTPUT = "history_output"
    HELP_OUTPUT = "help_output"


BOT_COMMAND_ALIASES = {
    "mute": {"мут", "м"},
    "unmute": {"анмут"},
    "kick": {"кик"},
    "ban": {"бан"},
    "unban": {"разбан"},
    "level": {"уровень"},
    "raise_level": {"повысить"},
    "lower_level": {"понизить"},
    "remove_level": {"снятьуровень"},
    "my_level": {"мойуровень"},
    "help": {"помощь", "help", "команды"},
    "moderators": {"модеры", "списокмодеров"},
    "info": {"инфо"},
    "history": {"история"},
    "active_mutes": {"муты"},
}

MODERATION_REQUIRED_LEVELS = {
    "mute": 2,
    "unmute": 2,
    "kick": 3,
    "ban": 4,
    "unban": 4,
    "view_level": 2,
    "manage_levels": 4,
    "moderators": 4,
    "info": 2,
    "history": 2,
    "active_mutes": 2,
}

SUPPORTED_GROUP_CHAT_TYPES = {ChatType.GROUP, ChatType.SUPERGROUP}
CHANNEL_CHAT_TYPES = {ChatType.CHANNEL}
PRIVATE_CHAT_TYPES = {ChatType.PRIVATE}

MAX_ADMIN_LEVEL = 5
MAX_ASSIGNABLE_ADMIN_LEVEL = 4
LEVEL_FOUR_ASSIGNMENT_CAP = 3
MIN_ADMIN_LEVEL = 0
MAX_REASON_LENGTH = 300
DEFAULT_MUTE_DURATION_SECONDS = 3600
TELEGRAM_FOREVER_WINDOW_MIN_SECONDS = 30
TELEGRAM_FOREVER_WINDOW_MAX_SECONDS = 366 * 24 * 60 * 60
DEFAULT_REASON = "Причина не указана"
ZERO_WIDTH_CHARACTERS = ("\u200b", "\u200c", "\u200d", "\ufeff")

HISTORY_ACTION_LABELS = {
    "mute": "мут",
    "unmute": "снятие мута",
    "kick": "кик",
    "ban": "бан",
    "unban": "разбан",
    "set_level": "изменение уровня",
    "remove_level": "снятие уровня",
}
