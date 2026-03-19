from __future__ import annotations

import asyncio
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties

from config import AppConfig, load_config
from database.db import Database
from database.migrations import run_migrations
from database.repositories import (
    AdminLevelsRepository,
    BansRepository,
    ChatsRepository,
    MessageRefsRepository,
    MutesRepository,
    PunishmentsRepository,
    UsersRepository,
)
from handlers import register_handlers
from middlewares import ErrorMiddleware, IngestMiddleware
from services import (
    ChatService,
    MessageService,
    ModerationService,
    ParserService,
    PermissionService,
    SchedulerService,
    ServiceContainer,
    UserResolutionService,
)


def configure_logging(config: AppConfig) -> None:
    logs_dir = Path("logs")
    logs_dir.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    file_handler = RotatingFileHandler(logs_dir / "moderationbot.log", maxBytes=5_242_880, backupCount=7, encoding="utf-8")
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(config.log_level)
    root_logger.handlers.clear()
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)


async def build_services(config: AppConfig) -> tuple[Database, ServiceContainer]:
    database = Database(config.database.path)
    await database.initialize()
    await run_migrations(database)

    chats_repo = ChatsRepository(database)
    users_repo = UsersRepository(database)
    message_refs_repo = MessageRefsRepository(database)
    admin_levels_repo = AdminLevelsRepository(database)
    punishments_repo = PunishmentsRepository(database)
    mutes_repo = MutesRepository(database)
    bans_repo = BansRepository(database)

    message_service = MessageService(config)
    user_resolution_service = UserResolutionService(
        database=database,
        chats_repo=chats_repo,
        users_repo=users_repo,
        message_refs_repo=message_refs_repo,
        message_service=message_service,
    )
    parser_service = ParserService()
    moderation_service = ModerationService(
        config=config,
        database=database,
        mutes_repo=mutes_repo,
        bans_repo=bans_repo,
        punishments_repo=punishments_repo,
        users_repo=users_repo,
        message_service=message_service,
    )
    scheduler_service = SchedulerService(
        config=config,
        database=database,
        moderation_service=moderation_service,
        mutes_repo=mutes_repo,
        bans_repo=bans_repo,
        punishments_repo=punishments_repo,
        message_refs_repo=message_refs_repo,
    )
    permission_service = PermissionService(
        database=database,
        admin_levels_repo=admin_levels_repo,
        chats_repo=chats_repo,
        punishments_repo=punishments_repo,
        users_repo=users_repo,
        message_service=message_service,
        system_owner_user_id=config.system_owner_user_id,
    )
    chat_service = ChatService(
        database=database,
        chats_repo=chats_repo,
        admin_levels_repo=admin_levels_repo,
        punishments_repo=punishments_repo,
        mutes_repo=mutes_repo,
        bans_repo=bans_repo,
        users_repo=users_repo,
        message_refs_repo=message_refs_repo,
        retry_config=config.retry,
        system_owner_user_id=config.system_owner_user_id,
    )

    services = ServiceContainer(
        chats=chat_service,
        messages=message_service,
        moderation=moderation_service,
        parser=parser_service,
        permissions=permission_service,
        scheduler=scheduler_service,
        users=user_resolution_service,
    )
    return database, services


async def main() -> None:
    config = load_config()
    configure_logging(config)
    logger = logging.getLogger(__name__)
    logger.info("Starting moderation bot")
    logger.info(
        "Runtime configuration | mode=long-polling | database=%s | system_owner_configured=%s",
        config.database.path,
        "yes" if config.system_owner_user_id is not None else "no",
    )

    _, services = await build_services(config)

    bot = Bot(
        token=config.bot_token,
        default=DefaultBotProperties(parse_mode=config.parse_mode),
    )
    dispatcher = Dispatcher()
    dispatcher["services"] = services
    dispatcher["config"] = config

    error_middleware = ErrorMiddleware()
    ingest_middleware = IngestMiddleware()
    dispatcher.message.outer_middleware(ingest_middleware)
    dispatcher.chat_member.outer_middleware(ingest_middleware)
    dispatcher.my_chat_member.outer_middleware(ingest_middleware)
    dispatcher.message.outer_middleware(error_middleware)
    dispatcher.chat_member.outer_middleware(error_middleware)
    dispatcher.my_chat_member.outer_middleware(error_middleware)

    register_handlers(dispatcher)

    await services.scheduler.recover(bot)
    services.scheduler.start(bot)

    try:
        await dispatcher.start_polling(bot, allowed_updates=dispatcher.resolve_used_update_types())
    finally:
        await services.scheduler.stop()
        await bot.session.close()
        logger.info("Moderation bot stopped")


if __name__ == "__main__":
    asyncio.run(main())
