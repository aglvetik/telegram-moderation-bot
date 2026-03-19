from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def build_future_confirmation_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Подтвердить", callback_data="noop:confirm"),
                InlineKeyboardButton(text="Отмена", callback_data="noop:cancel"),
            ]
        ]
    )
