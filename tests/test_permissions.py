from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from aiogram.enums import ChatMemberStatus, ChatType, ParseMode

from config import AppConfig, BackupConfig, DatabaseConfig, MessagePolicyConfig, RetryConfig, SchedulerConfig
from database.db import Database
from database.migrations import run_migrations
from database.repositories.admin_levels_repo import AdminLevelsRepository
from database.repositories.bans_repo import BansRepository
from database.repositories.chats_repo import ChatsRepository
from database.repositories.message_refs_repo import MessageRefsRepository
from database.repositories.mutes_repo import MutesRepository
from database.repositories.punishments_repo import PunishmentsRepository
from database.repositories.users_repo import UsersRepository
from services.chat_service import ChatService
from services.message_service import MessageService
from services.permission_service import PermissionService
from services.user_resolution_service import ResolvedUser
from utils.constants import MODERATION_REQUIRED_LEVELS


def build_test_config(*, system_owner_user_id: int | None = None) -> AppConfig:
    return AppConfig(
        bot_token="123456:TESTTOKEN",
        parse_mode=ParseMode.HTML,
        log_level="INFO",
        system_owner_user_id=system_owner_user_id,
        data_retention_days=90,
        history_limit=5,
        active_mutes_limit=20,
        database=DatabaseConfig(path=Path("test.sqlite3")),
        scheduler=SchedulerConfig(
            expired_mute_check_seconds=60,
            expired_ban_check_seconds=60,
            mute_verification_interval_seconds=300,
            cleanup_interval_seconds=86400,
            sqlite_backup_interval_seconds=21600,
        ),
        backup=BackupConfig(enabled=False, directory=Path("backups")),
        retry=RetryConfig(retries=0, base_delay_seconds=0.1),
        message_policy=MessagePolicyConfig(
            delete_command_messages=False,
            command_delete_delay_seconds=3,
            ordinary_message_delete_seconds=60,
        ),
    )


def make_member(user_id: int, *, status: ChatMemberStatus, can_restrict_members: bool = False):
    return SimpleNamespace(
        status=status,
        user=SimpleNamespace(id=user_id, username=f"user{user_id}", first_name=f"User {user_id}", last_name=None),
        can_restrict_members=can_restrict_members,
    )


class FakeBot:
    def __init__(self, member_map: dict[int, object], *, bot_id: int = 999) -> None:
        self.member_map = member_map
        self.id = bot_id

    async def get_chat_member(self, chat_id: int, user_id: int):
        return self.member_map.get(user_id)

    async def get_chat_administrators(self, chat_id: int):
        return []

    async def get_chat(self, chat_id: int):
        return SimpleNamespace(id=chat_id, type=ChatType.SUPERGROUP, title="Permissions chat")


class PermissionModelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.permission_service = PermissionService(
            database=None,
            admin_levels_repo=None,
            chats_repo=None,
            punishments_repo=None,
            users_repo=None,
            message_service=MessageService(build_test_config()),
            system_owner_user_id=None,
        )

    def test_level_requirements_match_updated_model(self) -> None:
        self.assertEqual(MODERATION_REQUIRED_LEVELS["mute"], 2)
        self.assertEqual(MODERATION_REQUIRED_LEVELS["unmute"], 2)
        self.assertEqual(MODERATION_REQUIRED_LEVELS["kick"], 3)
        self.assertEqual(MODERATION_REQUIRED_LEVELS["ban"], 4)
        self.assertEqual(MODERATION_REQUIRED_LEVELS["unban"], 4)
        self.assertEqual(MODERATION_REQUIRED_LEVELS["manage_levels"], 4)
        self.assertEqual(MODERATION_REQUIRED_LEVELS["moderators"], 4)

    def test_level_four_is_capped_to_assign_three(self) -> None:
        self.assertEqual(self.permission_service.max_manageable_assignment_for_actor(4), 3)

    def test_level_five_can_still_assign_four(self) -> None:
        self.assertEqual(self.permission_service.max_manageable_assignment_for_actor(5), 4)

    def test_level_four_cannot_assign_level_four(self) -> None:
        with self.assertRaises(Exception):
            self.permission_service.resolve_requested_level(
                actor_level=4,
                current_level=3,
                requested_level=4,
                requested_delta=None,
            )

    def test_level_four_cannot_raise_someone_to_four(self) -> None:
        with self.assertRaises(Exception):
            self.permission_service.resolve_requested_level(
                actor_level=4,
                current_level=3,
                requested_level=None,
                requested_delta=1,
            )

    def test_level_five_is_never_command_assignable(self) -> None:
        with self.assertRaises(Exception):
            self.permission_service.resolve_requested_level(
                actor_level=5,
                current_level=4,
                requested_level=5,
                requested_delta=None,
            )


class PermissionIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="moderationbot_permission_test_")
        self.database = Database(Path(self.temp_dir.name) / "test.sqlite3")
        await self.database.initialize()
        await run_migrations(self.database)

        self.chats_repo = ChatsRepository(self.database)
        self.admin_levels_repo = AdminLevelsRepository(self.database)
        self.message_refs_repo = MessageRefsRepository(self.database)
        self.mutes_repo = MutesRepository(self.database)
        self.bans_repo = BansRepository(self.database)
        self.punishments_repo = PunishmentsRepository(self.database)
        self.users_repo = UsersRepository(self.database)
        self.message_service = MessageService(build_test_config())
        self.chat_service = ChatService(
            database=self.database,
            chats_repo=self.chats_repo,
            admin_levels_repo=self.admin_levels_repo,
            punishments_repo=self.punishments_repo,
            mutes_repo=self.mutes_repo,
            bans_repo=self.bans_repo,
            users_repo=self.users_repo,
            message_refs_repo=self.message_refs_repo,
            retry_config=RetryConfig(retries=0, base_delay_seconds=0.1),
            system_owner_user_id=None,
        )
        self.permission_service = PermissionService(
            database=self.database,
            admin_levels_repo=self.admin_levels_repo,
            chats_repo=self.chats_repo,
            punishments_repo=self.punishments_repo,
            users_repo=self.users_repo,
            message_service=self.message_service,
            system_owner_user_id=None,
            chat_service=self.chat_service,
        )
        self.chat_id = -100500
        await self.chats_repo.upsert_chat(
            chat_id=self.chat_id,
            chat_type=ChatType.SUPERGROUP,
            title="Permissions chat",
            settings={},
        )

    async def asyncTearDown(self) -> None:
        self.temp_dir.cleanup()

    async def test_level_two_can_mute_without_being_telegram_admin(self) -> None:
        await self.admin_levels_repo.set_level(chat_id=self.chat_id, user_id=10, admin_level=2, granted_by_user_id=None)
        bot = FakeBot(
            {
                10: make_member(10, status=ChatMemberStatus.MEMBER),
                20: make_member(20, status=ChatMemberStatus.MEMBER),
                999: make_member(999, status=ChatMemberStatus.ADMINISTRATOR, can_restrict_members=True),
            }
        )
        result = await self.permission_service.ensure_moderation_allowed(
            bot=bot,
            chat_id=self.chat_id,
            actor=SimpleNamespace(id=10, username="lvl2", first_name="Lvl2", last_name=None),
            target=ResolvedUser(user_id=20, username="target", display_name="Target", member=make_member(20, status=ChatMemberStatus.MEMBER)),
            action="mute",
        )
        self.assertEqual(result[0], 2)

    async def test_level_three_can_kick_without_being_telegram_admin(self) -> None:
        await self.admin_levels_repo.set_level(chat_id=self.chat_id, user_id=11, admin_level=3, granted_by_user_id=None)
        bot = FakeBot(
            {
                11: make_member(11, status=ChatMemberStatus.MEMBER),
                21: make_member(21, status=ChatMemberStatus.MEMBER),
                999: make_member(999, status=ChatMemberStatus.ADMINISTRATOR, can_restrict_members=True),
            }
        )
        result = await self.permission_service.ensure_moderation_allowed(
            bot=bot,
            chat_id=self.chat_id,
            actor=SimpleNamespace(id=11, username="lvl3", first_name="Lvl3", last_name=None),
            target=ResolvedUser(user_id=21, username="target", display_name="Target", member=make_member(21, status=ChatMemberStatus.MEMBER)),
            action="kick",
        )
        self.assertEqual(result[0], 3)

    async def test_level_four_can_ban_without_being_telegram_admin(self) -> None:
        await self.admin_levels_repo.set_level(chat_id=self.chat_id, user_id=12, admin_level=4, granted_by_user_id=None)
        bot = FakeBot(
            {
                12: make_member(12, status=ChatMemberStatus.MEMBER),
                22: make_member(22, status=ChatMemberStatus.MEMBER),
                999: make_member(999, status=ChatMemberStatus.ADMINISTRATOR, can_restrict_members=True),
            }
        )
        result = await self.permission_service.ensure_moderation_allowed(
            bot=bot,
            chat_id=self.chat_id,
            actor=SimpleNamespace(id=12, username="lvl4", first_name="Lvl4", last_name=None),
            target=ResolvedUser(user_id=22, username="target", display_name="Target", member=make_member(22, status=ChatMemberStatus.MEMBER)),
            action="ban",
        )
        self.assertEqual(result[0], 4)

    async def test_level_two_cannot_mute_level_three(self) -> None:
        await self.admin_levels_repo.set_level(chat_id=self.chat_id, user_id=30, admin_level=2, granted_by_user_id=None)
        await self.admin_levels_repo.set_level(chat_id=self.chat_id, user_id=31, admin_level=3, granted_by_user_id=None)
        bot = FakeBot(
            {
                30: make_member(30, status=ChatMemberStatus.MEMBER),
                31: make_member(31, status=ChatMemberStatus.MEMBER),
                999: make_member(999, status=ChatMemberStatus.ADMINISTRATOR, can_restrict_members=True),
            }
        )
        with self.assertRaisesRegex(Exception, "таким же или более высоким уровнем"):
            await self.permission_service.ensure_moderation_allowed(
                bot=bot,
                chat_id=self.chat_id,
                actor=SimpleNamespace(id=30, username="lvl2", first_name="Lvl2", last_name=None),
                target=ResolvedUser(user_id=31, username="lvl3", display_name="Lvl3", member=make_member(31, status=ChatMemberStatus.MEMBER)),
                action="mute",
            )

    async def test_level_three_cannot_mute_level_four(self) -> None:
        await self.admin_levels_repo.set_level(chat_id=self.chat_id, user_id=32, admin_level=3, granted_by_user_id=None)
        await self.admin_levels_repo.set_level(chat_id=self.chat_id, user_id=33, admin_level=4, granted_by_user_id=None)
        bot = FakeBot(
            {
                32: make_member(32, status=ChatMemberStatus.MEMBER),
                33: make_member(33, status=ChatMemberStatus.MEMBER),
                999: make_member(999, status=ChatMemberStatus.ADMINISTRATOR, can_restrict_members=True),
            }
        )
        with self.assertRaisesRegex(Exception, "таким же или более высоким уровнем"):
            await self.permission_service.ensure_moderation_allowed(
                bot=bot,
                chat_id=self.chat_id,
                actor=SimpleNamespace(id=32, username="lvl3", first_name="Lvl3", last_name=None),
                target=ResolvedUser(user_id=33, username="lvl4", display_name="Lvl4", member=make_member(33, status=ChatMemberStatus.MEMBER)),
                action="mute",
            )

    async def test_level_four_cannot_mute_same_level_four(self) -> None:
        await self.admin_levels_repo.set_level(chat_id=self.chat_id, user_id=34, admin_level=4, granted_by_user_id=None)
        await self.admin_levels_repo.set_level(chat_id=self.chat_id, user_id=35, admin_level=4, granted_by_user_id=None)
        bot = FakeBot(
            {
                34: make_member(34, status=ChatMemberStatus.MEMBER),
                35: make_member(35, status=ChatMemberStatus.MEMBER),
                999: make_member(999, status=ChatMemberStatus.ADMINISTRATOR, can_restrict_members=True),
            }
        )
        with self.assertRaisesRegex(Exception, "таким же или более высоким уровнем"):
            await self.permission_service.ensure_moderation_allowed(
                bot=bot,
                chat_id=self.chat_id,
                actor=SimpleNamespace(id=34, username="lvl4", first_name="Lvl4", last_name=None),
                target=ResolvedUser(user_id=35, username="lvl4b", display_name="Lvl4b", member=make_member(35, status=ChatMemberStatus.MEMBER)),
                action="mute",
            )

    async def test_level_four_cannot_mute_level_five(self) -> None:
        await self.admin_levels_repo.set_level(chat_id=self.chat_id, user_id=36, admin_level=4, granted_by_user_id=None)
        await self.admin_levels_repo.set_level(chat_id=self.chat_id, user_id=37, admin_level=5, granted_by_user_id=None)
        bot = FakeBot(
            {
                36: make_member(36, status=ChatMemberStatus.MEMBER),
                37: make_member(37, status=ChatMemberStatus.MEMBER),
                999: make_member(999, status=ChatMemberStatus.ADMINISTRATOR, can_restrict_members=True),
            }
        )
        with self.assertRaisesRegex(Exception, "таким же или более высоким уровнем"):
            await self.permission_service.ensure_moderation_allowed(
                bot=bot,
                chat_id=self.chat_id,
                actor=SimpleNamespace(id=36, username="lvl4", first_name="Lvl4", last_name=None),
                target=ResolvedUser(user_id=37, username="lvl5", display_name="Lvl5", member=make_member(37, status=ChatMemberStatus.MEMBER)),
                action="mute",
            )

    async def test_level_five_cannot_sanction_another_level_five(self) -> None:
        await self.admin_levels_repo.set_level(chat_id=self.chat_id, user_id=38, admin_level=5, granted_by_user_id=None)
        owner_service = PermissionService(
            database=self.database,
            admin_levels_repo=self.admin_levels_repo,
            chats_repo=self.chats_repo,
            punishments_repo=self.punishments_repo,
            users_repo=self.users_repo,
            message_service=MessageService(build_test_config(system_owner_user_id=5300889569)),
            system_owner_user_id=5300889569,
            chat_service=self.chat_service,
        )
        bot = FakeBot(
            {
                5300889569: make_member(5300889569, status=ChatMemberStatus.MEMBER),
                38: make_member(38, status=ChatMemberStatus.MEMBER),
                999: make_member(999, status=ChatMemberStatus.ADMINISTRATOR, can_restrict_members=True),
            }
        )
        with self.assertRaisesRegex(Exception, "таким же или более высоким уровнем"):
            await owner_service.ensure_moderation_allowed(
                bot=bot,
                chat_id=self.chat_id,
                actor=SimpleNamespace(id=5300889569, username="owner", first_name="System", last_name="Owner"),
                target=ResolvedUser(user_id=38, username="lvl5", display_name="Lvl5", member=make_member(38, status=ChatMemberStatus.MEMBER)),
                action="ban",
            )

    async def test_valid_hierarchy_action_still_works(self) -> None:
        await self.admin_levels_repo.set_level(chat_id=self.chat_id, user_id=39, admin_level=4, granted_by_user_id=None)
        await self.admin_levels_repo.set_level(chat_id=self.chat_id, user_id=40, admin_level=3, granted_by_user_id=None)
        bot = FakeBot(
            {
                39: make_member(39, status=ChatMemberStatus.MEMBER),
                40: make_member(40, status=ChatMemberStatus.MEMBER),
                999: make_member(999, status=ChatMemberStatus.ADMINISTRATOR, can_restrict_members=True),
            }
        )
        result = await self.permission_service.ensure_moderation_allowed(
            bot=bot,
            chat_id=self.chat_id,
            actor=SimpleNamespace(id=39, username="lvl4", first_name="Lvl4", last_name=None),
            target=ResolvedUser(user_id=40, username="lvl3", display_name="Lvl3", member=make_member(40, status=ChatMemberStatus.MEMBER)),
            action="ban",
        )
        self.assertEqual(result, (4, 3))

    async def test_level_changes_also_respect_strict_hierarchy(self) -> None:
        await self.admin_levels_repo.set_level(chat_id=self.chat_id, user_id=41, admin_level=4, granted_by_user_id=None)
        await self.admin_levels_repo.set_level(chat_id=self.chat_id, user_id=42, admin_level=4, granted_by_user_id=None)
        bot = FakeBot(
            {
                41: make_member(41, status=ChatMemberStatus.MEMBER),
                42: make_member(42, status=ChatMemberStatus.MEMBER),
                999: make_member(999, status=ChatMemberStatus.ADMINISTRATOR, can_restrict_members=True),
            }
        )
        with self.assertRaisesRegex(Exception, "таким же или более высоким уровнем"):
            await self.permission_service.ensure_manage_levels_allowed(
                bot=bot,
                chat_id=self.chat_id,
                actor=SimpleNamespace(id=41, username="lvl4", first_name="Lvl4", last_name=None),
                target=ResolvedUser(user_id=42, username="lvl4b", display_name="Lvl4b"),
            )

    async def test_bot_rights_are_still_required(self) -> None:
        await self.admin_levels_repo.set_level(chat_id=self.chat_id, user_id=13, admin_level=2, granted_by_user_id=None)
        bot = FakeBot(
            {
                13: make_member(13, status=ChatMemberStatus.MEMBER),
                23: make_member(23, status=ChatMemberStatus.MEMBER),
                999: make_member(999, status=ChatMemberStatus.MEMBER, can_restrict_members=False),
            }
        )
        with self.assertRaises(Exception):
            await self.permission_service.ensure_moderation_allowed(
                bot=bot,
                chat_id=self.chat_id,
                actor=SimpleNamespace(id=13, username="lvl2", first_name="Lvl2", last_name=None),
                target=ResolvedUser(user_id=23, username="target", display_name="Target", member=make_member(23, status=ChatMemberStatus.MEMBER)),
                action="mute",
            )

    async def test_system_owner_always_has_effective_level_five_across_chats(self) -> None:
        owner_service = PermissionService(
            database=self.database,
            admin_levels_repo=self.admin_levels_repo,
            chats_repo=self.chats_repo,
            punishments_repo=self.punishments_repo,
            users_repo=self.users_repo,
            message_service=MessageService(build_test_config(system_owner_user_id=5300889569)),
            system_owner_user_id=5300889569,
            chat_service=self.chat_service,
        )
        other_chat_id = -100501
        await self.chats_repo.upsert_chat(
            chat_id=other_chat_id,
            chat_type=ChatType.SUPERGROUP,
            title="Other chat",
            settings={},
        )
        self.assertEqual(await owner_service.get_effective_level(self.chat_id, 5300889569), 5)
        self.assertEqual(await owner_service.get_effective_level(other_chat_id, 5300889569), 5)

    async def test_system_owner_public_level_does_not_leak_hidden_five(self) -> None:
        owner_service = PermissionService(
            database=self.database,
            admin_levels_repo=self.admin_levels_repo,
            chats_repo=self.chats_repo,
            punishments_repo=self.punishments_repo,
            users_repo=self.users_repo,
            message_service=MessageService(build_test_config(system_owner_user_id=5300889569)),
            system_owner_user_id=5300889569,
            chat_service=self.chat_service,
        )
        self.assertEqual(await owner_service.get_my_level(self.chat_id, SimpleNamespace(id=5300889569)), 0)
        self.assertEqual(await owner_service.get_effective_level(self.chat_id, 5300889569), 5)

    async def test_real_chat_owner_has_public_and_effective_level_five(self) -> None:
        await self.chats_repo.update_owner(self.chat_id, 77)
        self.assertEqual(await self.permission_service.get_level(self.chat_id, 77), 5)
        self.assertEqual(await self.permission_service.get_my_level(self.chat_id, SimpleNamespace(id=77)), 5)
        self.assertEqual(await self.permission_service.get_effective_level(self.chat_id, 77), 5)

    async def test_chat_owner_fallback_works_without_admin_levels_row(self) -> None:
        await self.chats_repo.update_owner(self.chat_id, 78)
        self.assertEqual(await self.admin_levels_repo.get_level(self.chat_id, 78), 0)
        self.assertEqual(await self.permission_service.get_level(self.chat_id, 78), 5)
        self.assertEqual(await self.permission_service.get_my_level(self.chat_id, SimpleNamespace(id=78)), 5)
        self.assertEqual(await self.permission_service.get_effective_level(self.chat_id, 78), 5)

    async def test_lazy_owner_refresh_repairs_missing_owner_for_my_level(self) -> None:
        bot = FakeBot(
            {
                79: make_member(79, status=ChatMemberStatus.CREATOR),
                999: make_member(999, status=ChatMemberStatus.ADMINISTRATOR, can_restrict_members=True),
            }
        )

        level = await self.permission_service.get_my_level(self.chat_id, SimpleNamespace(id=79), bot=bot)
        self.assertEqual(level, 5)
        chat = await self.chats_repo.get_chat(self.chat_id)
        self.assertIsNotNone(chat)
        self.assertEqual(chat.owner_user_id, 79)
        self.assertEqual(await self.admin_levels_repo.get_level(self.chat_id, 79), 5)

    async def test_lazy_owner_refresh_repairs_missing_owner_for_level_info(self) -> None:
        owner_member = make_member(80, status=ChatMemberStatus.CREATOR)
        bot = FakeBot(
            {
                80: owner_member,
                999: make_member(999, status=ChatMemberStatus.ADMINISTRATOR, can_restrict_members=True),
            }
        )

        level = await self.permission_service.get_level(self.chat_id, 80, bot=bot, member=owner_member)
        self.assertEqual(level, 5)
        chat = await self.chats_repo.get_chat(self.chat_id)
        self.assertIsNotNone(chat)
        self.assertEqual(chat.owner_user_id, 80)

    async def test_real_chat_owner_can_pass_moderation_permission_checks(self) -> None:
        bot = FakeBot(
            {
                81: make_member(81, status=ChatMemberStatus.CREATOR),
                82: make_member(82, status=ChatMemberStatus.MEMBER),
                999: make_member(999, status=ChatMemberStatus.ADMINISTRATOR, can_restrict_members=True),
            }
        )

        result = await self.permission_service.ensure_moderation_allowed(
            bot=bot,
            chat_id=self.chat_id,
            actor=SimpleNamespace(id=81, username="owner81", first_name="Owner", last_name=None),
            target=ResolvedUser(user_id=82, username="target82", display_name="Target 82", member=make_member(82, status=ChatMemberStatus.MEMBER)),
            action="mute",
        )
        self.assertEqual(result[0], 5)
        chat = await self.chats_repo.get_chat(self.chat_id)
        self.assertIsNotNone(chat)
        self.assertEqual(chat.owner_user_id, 81)

    async def test_real_chat_owner_can_pass_level_management_checks(self) -> None:
        bot = FakeBot(
            {
                83: make_member(83, status=ChatMemberStatus.CREATOR),
                84: make_member(84, status=ChatMemberStatus.MEMBER),
                999: make_member(999, status=ChatMemberStatus.ADMINISTRATOR, can_restrict_members=True),
            }
        )

        result = await self.permission_service.ensure_manage_levels_allowed(
            bot=bot,
            chat_id=self.chat_id,
            actor=SimpleNamespace(id=83, username="owner83", first_name="Owner", last_name=None),
            target=ResolvedUser(user_id=84, username="target84", display_name="Target 84"),
        )
        self.assertEqual(result[0], 5)
        chat = await self.chats_repo.get_chat(self.chat_id)
        self.assertIsNotNone(chat)
        self.assertEqual(chat.owner_user_id, 83)

    async def test_system_owner_permission_override_works_without_db_assignment(self) -> None:
        owner_service = PermissionService(
            database=self.database,
            admin_levels_repo=self.admin_levels_repo,
            chats_repo=self.chats_repo,
            punishments_repo=self.punishments_repo,
            users_repo=self.users_repo,
            message_service=MessageService(build_test_config(system_owner_user_id=5300889569)),
            system_owner_user_id=5300889569,
            chat_service=self.chat_service,
        )
        bot = FakeBot(
            {
                5300889569: make_member(5300889569, status=ChatMemberStatus.MEMBER),
                24: make_member(24, status=ChatMemberStatus.MEMBER),
                999: make_member(999, status=ChatMemberStatus.ADMINISTRATOR, can_restrict_members=True),
            }
        )
        result = await owner_service.ensure_moderation_allowed(
            bot=bot,
            chat_id=self.chat_id,
            actor=SimpleNamespace(id=5300889569, username="owner", first_name="System", last_name="Owner"),
            target=ResolvedUser(user_id=24, username="target", display_name="Target", member=make_member(24, status=ChatMemberStatus.MEMBER)),
            action="ban",
        )
        self.assertEqual(result[0], 5)

    async def test_system_owner_still_respects_bot_rights(self) -> None:
        owner_service = PermissionService(
            database=self.database,
            admin_levels_repo=self.admin_levels_repo,
            chats_repo=self.chats_repo,
            punishments_repo=self.punishments_repo,
            users_repo=self.users_repo,
            message_service=MessageService(build_test_config(system_owner_user_id=5300889569)),
            system_owner_user_id=5300889569,
            chat_service=self.chat_service,
        )
        bot = FakeBot(
            {
                5300889569: make_member(5300889569, status=ChatMemberStatus.MEMBER),
                25: make_member(25, status=ChatMemberStatus.MEMBER),
                999: make_member(999, status=ChatMemberStatus.MEMBER, can_restrict_members=False),
            }
        )
        with self.assertRaises(Exception):
            await owner_service.ensure_moderation_allowed(
                bot=bot,
                chat_id=self.chat_id,
                actor=SimpleNamespace(id=5300889569, username="owner", first_name="System", last_name="Owner"),
                target=ResolvedUser(user_id=25, username="target", display_name="Target", member=make_member(25, status=ChatMemberStatus.MEMBER)),
                action="mute",
            )

    async def test_system_owner_has_no_special_moderation_immunity(self) -> None:
        await self.admin_levels_repo.set_level(chat_id=self.chat_id, user_id=14, admin_level=2, granted_by_user_id=None)
        owner_service = PermissionService(
            database=self.database,
            admin_levels_repo=self.admin_levels_repo,
            chats_repo=self.chats_repo,
            punishments_repo=self.punishments_repo,
            users_repo=self.users_repo,
            message_service=MessageService(build_test_config(system_owner_user_id=5300889569)),
            system_owner_user_id=5300889569,
            chat_service=self.chat_service,
        )
        bot = FakeBot(
            {
                14: make_member(14, status=ChatMemberStatus.MEMBER),
                5300889569: make_member(5300889569, status=ChatMemberStatus.MEMBER),
                999: make_member(999, status=ChatMemberStatus.ADMINISTRATOR, can_restrict_members=True),
            }
        )
        result = await owner_service.ensure_moderation_allowed(
            bot=bot,
            chat_id=self.chat_id,
            actor=SimpleNamespace(id=14, username="lvl2", first_name="Lvl2", last_name=None),
            target=ResolvedUser(
                user_id=5300889569,
                username="owner",
                display_name="System Owner",
                member=make_member(5300889569, status=ChatMemberStatus.MEMBER),
            ),
            action="mute",
        )
        self.assertEqual(result[0], 2)
        self.assertEqual(result[1], 0)


if __name__ == "__main__":
    unittest.main()
