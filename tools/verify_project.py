from __future__ import annotations

import asyncio
import compileall
import importlib
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

EXPECTED_PATHS = [
    "main.py",
    "config.py",
    "requirements.txt",
    ".env.example",
    "README.md",
    "handlers",
    "services",
    "database",
    "utils",
    "filters",
    "middlewares",
    "keyboards",
]

REQUIRED_ENV_KEYS = {
    "BOT_TOKEN",
    "SYSTEM_OWNER_USER_ID",
    "DATABASE_PATH",
    "LOG_LEVEL",
    "DELETE_COMMAND_MESSAGES",
    "DELETE_COMMAND_DELAY_SECONDS",
    "ORDINARY_MESSAGE_DELETE_SECONDS",
    "EXPIRED_MUTE_CHECK_SECONDS",
    "EXPIRED_BAN_CHECK_SECONDS",
    "MUTE_VERIFICATION_INTERVAL_SECONDS",
    "CLEANUP_INTERVAL_SECONDS",
    "SQLITE_BACKUP_ENABLED",
    "SQLITE_BACKUP_INTERVAL_SECONDS",
    "SQLITE_BACKUP_DIR",
    "DATA_RETENTION_DAYS",
    "RATE_LIMIT_RETRIES",
    "RATE_LIMIT_BASE_DELAY_SECONDS",
    "HISTORY_LIMIT",
    "ACTIVE_MUTES_LIMIT",
}


def verify_structure() -> None:
    missing = [path for path in EXPECTED_PATHS if not (ROOT / path).exists()]
    if missing:
        raise AssertionError(f"Missing required paths: {missing}")
    print("STRUCTURE_OK")


def verify_env_example() -> None:
    env_path = ROOT / ".env.example"
    keys = set()
    values: dict[str, str] = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        keys.add(key)
        values[key] = value.strip()
    missing = REQUIRED_ENV_KEYS - keys
    if missing:
        raise AssertionError(f".env.example is missing keys: {sorted(missing)}")
    bot_token_value = values.get("BOT_TOKEN", "")
    if re.fullmatch(r"\d{6,}:[A-Za-z0-9_-]{20,}", bot_token_value):
        raise AssertionError(".env.example must not contain a real Telegram bot token")
    owner_value = values.get("SYSTEM_OWNER_USER_ID", "")
    if owner_value and not owner_value.isdigit():
        raise AssertionError("SYSTEM_OWNER_USER_ID in .env.example must be numeric")
    print("ENV_EXAMPLE_OK")


def verify_compile() -> None:
    ok = compileall.compile_dir(
        str(ROOT),
        quiet=1,
        rx=re.compile(r".*[\\/]\.venv[\\/].*"),
    )
    if not ok:
        raise AssertionError("compileall reported failures")
    print("COMPILE_OK")


def verify_imports() -> None:
    failures: list[str] = []
    for path in ROOT.rglob("*.py"):
        if ".venv" in path.parts or "__pycache__" in path.parts:
            continue
        rel = path.relative_to(ROOT)
        if rel.name == "__init__.py":
            module = ".".join(rel.with_suffix("").parts[:-1])
        else:
            module = ".".join(rel.with_suffix("").parts)
        if not module:
            continue
        try:
            importlib.import_module(module)
        except Exception as exc:
            failures.append(f"{module}: {exc!r}")
    if failures:
        raise AssertionError("Import failures:\n" + "\n".join(failures))
    print("IMPORTS_OK")


async def verify_safe_startup() -> None:
    from aiogram import Bot, Dispatcher
    from aiogram.client.default import DefaultBotProperties

    from config import load_config
    from handlers import register_handlers
    from main import build_services

    with tempfile.TemporaryDirectory(prefix="moderationbot_verify_") as temp_dir:
        os.environ["BOT_TOKEN"] = "123456:TESTTOKEN"
        os.environ["DATABASE_PATH"] = str(Path(temp_dir) / "verify.sqlite3")
        os.environ["SQLITE_BACKUP_ENABLED"] = "false"
        config = load_config()
        _, services = await build_services(config)
        bot = Bot(token=config.bot_token, default=DefaultBotProperties(parse_mode=config.parse_mode))
        dispatcher = Dispatcher()
        dispatcher["services"] = services
        dispatcher["config"] = config
        register_handlers(dispatcher)
        await services.scheduler.recover(bot)
        services.scheduler.start(bot)
        await asyncio.sleep(0.05)
        await services.scheduler.stop()
        await bot.session.close()
    print("SAFE_STARTUP_OK")


def verify_main_startup_path() -> None:
    with tempfile.TemporaryDirectory(prefix="moderationbot_main_verify_") as temp_dir:
        env = os.environ.copy()
        env["BOT_TOKEN"] = "123456:TESTTOKEN"
        env["DATABASE_PATH"] = str(Path(temp_dir) / "main_verify.sqlite3")
        env["SQLITE_BACKUP_ENABLED"] = "false"
        harness = """
import asyncio
from unittest.mock import AsyncMock, patch

async def fake_start_polling(*args, **kwargs):
    assert args
    bot = args[0] if len(args) == 1 else args[1]
    assert bot is not None
    assert "allowed_updates" in kwargs
    return None

async def run():
    with patch("aiogram.Dispatcher.start_polling", new=AsyncMock(side_effect=fake_start_polling)):
        import main as app_main
        await app_main.main()

asyncio.run(run())
"""
        result = subprocess.run(
            [sys.executable, "-c", harness],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise AssertionError(
                "main startup path verification failed:\n"
                f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
            )
    print("MAIN_STARTUP_PATH_OK")


def verify_tests() -> None:
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise AssertionError("Unit tests failed")
    print("UNIT_TESTS_OK")


def main() -> None:
    verify_structure()
    verify_env_example()
    verify_compile()
    verify_imports()
    asyncio.run(verify_safe_startup())
    verify_main_startup_path()
    verify_tests()
    print("PROJECT_VERIFICATION_OK")


if __name__ == "__main__":
    main()
