from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from aiogram.enums import ParseMode
from dotenv import load_dotenv


@dataclass(slots=True)
class RetryConfig:
    retries: int
    base_delay_seconds: float


@dataclass(slots=True)
class SchedulerConfig:
    expired_mute_check_seconds: int
    mute_verification_interval_seconds: int
    cleanup_interval_seconds: int
    sqlite_backup_interval_seconds: int


@dataclass(slots=True)
class BackupConfig:
    enabled: bool
    directory: Path


@dataclass(slots=True)
class DatabaseConfig:
    path: Path


@dataclass(slots=True)
class MessagePolicyConfig:
    delete_command_messages: bool
    command_delete_delay_seconds: int
    ordinary_message_delete_seconds: int


@dataclass(slots=True)
class AppConfig:
    bot_token: str
    parse_mode: ParseMode
    log_level: str
    system_owner_user_id: int | None
    data_retention_days: int
    history_limit: int
    active_mutes_limit: int
    database: DatabaseConfig
    scheduler: SchedulerConfig
    backup: BackupConfig
    retry: RetryConfig
    message_policy: MessagePolicyConfig


def _get_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _get_int(name: str, default: int, minimum: int = 0) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    value = int(raw)
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return value


def _get_optional_int(name: str, minimum: int | None = None) -> int | None:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return None
    value = int(raw)
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return value


def _get_float(name: str, default: float, minimum: float = 0.0) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    value = float(raw)
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return value


def load_config() -> AppConfig:
    load_dotenv()

    bot_token = os.getenv("BOT_TOKEN", "").strip()
    if not bot_token:
        raise ValueError("BOT_TOKEN is required")

    database_path = Path(os.getenv("DATABASE_PATH", "moderationbot.sqlite3")).expanduser()
    backup_dir = Path(os.getenv("SQLITE_BACKUP_DIR", "backups")).expanduser()

    return AppConfig(
        bot_token=bot_token,
        parse_mode=ParseMode.HTML,
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        system_owner_user_id=_get_optional_int("SYSTEM_OWNER_USER_ID", minimum=1),
        data_retention_days=_get_int("DATA_RETENTION_DAYS", 90, minimum=1),
        history_limit=_get_int("HISTORY_LIMIT", 5, minimum=1),
        active_mutes_limit=_get_int("ACTIVE_MUTES_LIMIT", 20, minimum=1),
        database=DatabaseConfig(path=database_path),
        scheduler=SchedulerConfig(
            expired_mute_check_seconds=_get_int("EXPIRED_MUTE_CHECK_SECONDS", 60, minimum=10),
            mute_verification_interval_seconds=_get_int("MUTE_VERIFICATION_INTERVAL_SECONDS", 300, minimum=30),
            cleanup_interval_seconds=_get_int("CLEANUP_INTERVAL_SECONDS", 86400, minimum=300),
            sqlite_backup_interval_seconds=_get_int("SQLITE_BACKUP_INTERVAL_SECONDS", 21600, minimum=300),
        ),
        backup=BackupConfig(
            enabled=_get_bool("SQLITE_BACKUP_ENABLED", True),
            directory=backup_dir,
        ),
        retry=RetryConfig(
            retries=_get_int("RATE_LIMIT_RETRIES", 3, minimum=0),
            base_delay_seconds=_get_float("RATE_LIMIT_BASE_DELAY_SECONDS", 1.5, minimum=0.1),
        ),
        message_policy=MessagePolicyConfig(
            delete_command_messages=_get_bool("DELETE_COMMAND_MESSAGES", False),
            command_delete_delay_seconds=_get_int("DELETE_COMMAND_DELAY_SECONDS", 3, minimum=0),
            ordinary_message_delete_seconds=_get_int("ORDINARY_MESSAGE_DELETE_SECONDS", 60, minimum=1),
        ),
    )
