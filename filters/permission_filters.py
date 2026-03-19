from __future__ import annotations

from aiogram.filters import BaseFilter
from aiogram.types import Message

from utils.validators import extract_command_keyword


class PlainCommandFilter(BaseFilter):
    def __init__(self, commands: set[str]) -> None:
        self.commands = {command.lower() for command in commands}

    async def __call__(self, message: Message) -> bool:
        if not message.text:
            return False
        return extract_command_keyword(message.text) in self.commands
