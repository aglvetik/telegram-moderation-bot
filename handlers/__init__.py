from aiogram import Dispatcher

from handlers import admin_levels, chat_events, help_commands, info_commands, moderation


def register_handlers(dispatcher: Dispatcher) -> None:
    dispatcher.include_router(chat_events.router)
    dispatcher.include_router(help_commands.router)
    dispatcher.include_router(admin_levels.router)
    dispatcher.include_router(info_commands.router)
    dispatcher.include_router(moderation.router)
