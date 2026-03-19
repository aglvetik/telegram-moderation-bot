from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from pathlib import Path

from aiogram import Bot

from config import AppConfig
from database.db import Database
from database.repositories.bans_repo import BansRepository
from database.repositories.message_refs_repo import MessageRefsRepository
from database.repositories.mutes_repo import MutesRepository
from database.repositories.punishments_repo import PunishmentsRepository
from services.moderation_service import ModerationService
from utils.formatters import to_iso, utc_now


class SchedulerService:
    def __init__(
        self,
        *,
        config: AppConfig,
        database: Database,
        moderation_service: ModerationService,
        mutes_repo: MutesRepository,
        bans_repo: BansRepository,
        punishments_repo: PunishmentsRepository,
        message_refs_repo: MessageRefsRepository,
    ) -> None:
        self.config = config
        self.database = database
        self.moderation_service = moderation_service
        self.mutes_repo = mutes_repo
        self.bans_repo = bans_repo
        self.punishments_repo = punishments_repo
        self.message_refs_repo = message_refs_repo
        self.logger = logging.getLogger(__name__)
        self._stop_event = asyncio.Event()
        self._tasks: list[asyncio.Task] = []

    async def recover(self, bot: Bot) -> None:
        self.logger.info("Starting mute recovery pass")
        expired = await self.mutes_repo.list_expired_mutes(to_iso(utc_now()) or "")
        for mute in expired:
            try:
                await self.moderation_service.expire_mute(bot=bot, mute=mute)
            except Exception:
                self.logger.exception("Failed to expire mute during recovery for user %s in chat %s", mute.user_id, mute.chat_id)

        active = await self.mutes_repo.list_active_mutes()
        for mute in active:
            try:
                await self.moderation_service.verify_active_mute(bot=bot, mute=mute)
            except Exception:
                self.logger.exception("Failed to verify mute during recovery for user %s in chat %s", mute.user_id, mute.chat_id)

    def start(self, bot: Bot) -> None:
        self._stop_event.clear()
        self._tasks = [
            asyncio.create_task(
                self._loop(
                    "expired-mutes",
                    self.config.scheduler.expired_mute_check_seconds,
                    lambda: self._process_expired_mutes(bot),
                )
            ),
            asyncio.create_task(
                self._loop(
                    "verify-mutes",
                    self.config.scheduler.mute_verification_interval_seconds,
                    lambda: self._verify_active_mutes(bot),
                )
            ),
            asyncio.create_task(
                self._loop(
                    "cleanup",
                    self.config.scheduler.cleanup_interval_seconds,
                    self._cleanup_old_data,
                )
            ),
        ]
        if self.config.backup.enabled:
            self._tasks.append(
                asyncio.create_task(
                    self._loop(
                        "backup",
                        self.config.scheduler.sqlite_backup_interval_seconds,
                        self._create_backup,
                    )
                )
            )

    async def stop(self) -> None:
        self._stop_event.set()
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    async def _loop(self, name: str, interval_seconds: int, handler) -> None:
        self.logger.info("Scheduler task %s started", name)
        try:
            while not self._stop_event.is_set():
                try:
                    await handler()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    self.logger.exception("Scheduler task %s failed", name)
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=interval_seconds)
                except asyncio.TimeoutError:
                    continue
        except asyncio.CancelledError:
            self.logger.info("Scheduler task %s cancelled", name)

    async def _process_expired_mutes(self, bot: Bot) -> None:
        expired = await self.mutes_repo.list_expired_mutes(to_iso(utc_now()) or "")
        for mute in expired:
            try:
                await self.moderation_service.expire_mute(bot=bot, mute=mute)
            except Exception:
                self.logger.exception("Failed to process expired mute for user %s in chat %s", mute.user_id, mute.chat_id)

    async def _verify_active_mutes(self, bot: Bot) -> None:
        active = await self.mutes_repo.list_active_mutes()
        for mute in active:
            try:
                await self.moderation_service.verify_active_mute(bot=bot, mute=mute)
            except Exception:
                self.logger.exception("Failed to verify mute for user %s in chat %s", mute.user_id, mute.chat_id)

    async def _cleanup_old_data(self) -> None:
        cutoff = utc_now() - timedelta(days=self.config.data_retention_days)
        cutoff_iso = to_iso(cutoff) or ""
        async with self.database.transaction() as connection:
            await self.punishments_repo.cleanup_old_records(cutoff_iso, connection=connection)
            await self.mutes_repo.cleanup_old_records(cutoff_iso, connection=connection)
            await self.bans_repo.cleanup_old_records(cutoff_iso, connection=connection)
            await self.message_refs_repo.cleanup_old_records(cutoff_iso, connection=connection)
        self.logger.info("Old moderation data cleaned up before %s", cutoff_iso)

    async def _create_backup(self) -> None:
        timestamp = utc_now().strftime("%Y%m%d_%H%M%S")
        destination = Path(self.config.backup.directory) / f"moderationbot_{timestamp}.sqlite3"
        await asyncio.to_thread(self.database.create_backup, destination)
        self.logger.info("SQLite backup created at %s", destination)
