from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from aiogram.enums import ParseMode

from config import AppConfig, BackupConfig, DatabaseConfig, MessagePolicyConfig, RetryConfig, SchedulerConfig
from services.message_service import MessageService
from services.user_resolution_service import ResolvedUser
from utils.constants import MessageCategory


def build_config() -> AppConfig:
    return AppConfig(
        bot_token="123456:TESTTOKEN",
        parse_mode=ParseMode.HTML,
        log_level="INFO",
        system_owner_user_id=5300889569,
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


class MessageServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = MessageService(build_config())
        self.user = ResolvedUser(user_id=1, username="user", display_name="Test User")

    def test_permanent_mute_messages_use_bessrochno(self) -> None:
        mute_text = self.service.mute_success(self.user, self.user, None, "Причина не указана")
        self.assertIn("бессрочно", mute_text)
        already_text = self.service.mute_already_active(self.user, None)
        self.assertIn("бессрочно", already_text)

    def test_private_start_message_matches_expected_sections(self) -> None:
        text = self.service.private_start()
        self.assertIn("🤖 <b>Привет! Я — бот модерации для Telegram-групп.</b>", text)
        self.assertIn("<b>Что я умею:</b>", text)
        self.assertIn("<b>Как начать:</b>", text)
        self.assertIn("Некоторые функции Telegram зависят от ограничений Bot API", text)

    def test_welcome_and_help_messages_match_fixed_wording(self) -> None:
        self.assertIn("👋 <b>Всем привет! Я — бот модерации и уже готов к работе.</b>", self.service.welcome_group())
        self.assertIn("ℹ️ <b>Я добавлен в канал.</b>", self.service.welcome_channel())
        help_text = self.service.help_message(4)
        self.assertIn("ℹ️ <b>Справка по командам бота</b>", help_text)
        self.assertIn("• <code>мут</code> / <code>м</code> — выдать мут", help_text)
        self.assertIn("• <code>повысить</code>", help_text)
        self.assertIn("• <code>бан</code> — заблокировать пользователя", help_text)

    def test_help_message_is_filtered_by_level(self) -> None:
        level_one_help = self.service.help_message(1)
        self.assertNotIn("<b>Информация:</b>", level_one_help)
        self.assertNotIn("<code>мут</code>", level_one_help)
        self.assertNotIn("<code>бан</code>", level_one_help)

        level_two_help = self.service.help_message(2)
        self.assertIn("<b>Информация:</b>", level_two_help)
        self.assertIn("<code>мут</code> / <code>м</code>", level_two_help)
        self.assertNotIn("<code>кик</code> — удалить пользователя из чата", level_two_help)
        self.assertNotIn("<code>бан</code> — заблокировать пользователя", level_two_help)

        level_three_help = self.service.help_message(3)
        self.assertIn("<code>кик</code> — удалить пользователя из чата", level_three_help)
        self.assertNotIn("<code>повысить</code>", level_three_help)

    def test_level_zero_help_uses_short_neutral_text(self) -> None:
        text = self.service.help_unavailable_for_level_zero()
        self.assertIn("Полная справка по модерации доступна только назначенным модераторам.", text)
        self.assertNotIn("<code>мут</code>", text)

    def test_group_and_channel_limit_messages_match_required_text(self) -> None:
        self.assertEqual(self.service.moderation_groups_only(), "ℹ️ Эта команда работает только в группах и супергруппах.")
        self.assertEqual(self.service.moderation_channels_only(), "ℹ️ Команды модерации пользователей недоступны в каналах.")

    def test_common_error_messages_match_required_text(self) -> None:
        self.assertIn("❌ <b>Недостаточно прав для выполнения команды.</b>", self.service.insufficient_level(4))
        self.assertIn("Требуемый уровень модерации: <b>4</b>", self.service.insufficient_level(4))
        self.assertIn("❌ <b>Не удалось определить пользователя.</b>", self.service.target_not_found())
        self.assertIn("• ответом на сообщение", self.service.target_not_found())
        self.assertIn("❌ <b>Пользователь по указанному username не найден.</b>", self.service.username_resolution_failed())
        self.assertIn("❌ <b>Боту не хватает прав для выполнения этого действия.</b>", self.service.bot_lacks_rights())
        self.assertEqual(self.service.target_is_bot(), "❌ Нельзя применять это действие к самому боту.")
        self.assertEqual(self.service.target_is_self(), "❌ Нельзя применять это действие к самому себе.")
        expected_hierarchy_text = "❌ Нельзя применить действие к пользователю с таким же или более высоким уровнем."
        self.assertEqual(self.service.target_higher_level(), expected_hierarchy_text)
        self.assertEqual(self.service.target_equal_level(), expected_hierarchy_text)
        self.assertEqual(self.service.target_same_or_higher_level(), expected_hierarchy_text)
        self.assertEqual(
            self.service.target_admin_protected(),
            "❌ Невозможно выполнить действие.\nЭтот пользователь является администратором.",
        )
        self.assertIn("Telegram ограничил выполнение операции", self.service.generic_action_failed())
        self.assertIn("Обнаружены две разные цели команды.", self.service.conflicting_targets())

    def test_info_outputs_match_fixed_wording(self) -> None:
        self.assertEqual(
            self.service.my_level(5),
            "ℹ️ <b>Ваш уровень модерации:</b> 5\n\n"
            "Чем выше уровень, тем больше доступных возможностей управления чатом.",
        )
        self.assertEqual(self.service.level_info(self.user, 3), "ℹ️ <b>Уровень модерации пользователя:</b> 3")
        self.assertEqual(self.service.moderators_list([]), "ℹ️ В этом чате пока нет назначенных модераторов.")
        moderators_text = self.service.moderators_list([(self.user, 3)])
        self.assertIn("🛡 <b>Список модераторов чата:</b>", moderators_text)
        self.assertIn("уровень <b>3</b>", moderators_text)

    def test_history_and_active_mutes_match_fixed_headers(self) -> None:
        empty_history = self.service.history(self.user, [])
        self.assertIn("📚 <b>История модерации пользователя</b>", empty_history)
        self.assertIn("Далее перечисляются последние действия модераторов.", empty_history)
        self.assertIn("Записей пока нет.", empty_history)
        self.assertEqual(self.service.active_mutes([]), "ℹ️ Сейчас в этом чате нет активных мутов.")


class MessageServiceSendingTests(unittest.IsolatedAsyncioTestCase):
    async def test_bot_reply_is_not_scheduled_for_auto_delete(self) -> None:
        service = MessageService(build_config())
        sent = SimpleNamespace(chat=SimpleNamespace(id=-1001), message_id=123)
        message = SimpleNamespace(answer=AsyncMock(return_value=sent))
        bot = SimpleNamespace()

        with patch("services.message_service.asyncio.create_task") as create_task_mock:
            result = await service.reply(
                bot=bot,
                message=message,
                text="test",
                category=MessageCategory.TRANSIENT_ERROR,
            )

        self.assertIs(result, sent)
        message.answer.assert_awaited_once_with("test")
        create_task_mock.assert_not_called()

    async def test_bot_send_to_chat_is_not_scheduled_for_auto_delete(self) -> None:
        service = MessageService(build_config())
        sent = SimpleNamespace(chat=SimpleNamespace(id=-1001), message_id=124)
        bot = SimpleNamespace(send_message=AsyncMock(return_value=sent))

        with patch("services.message_service.asyncio.create_task") as create_task_mock:
            result = await service.send_to_chat(
                bot=bot,
                chat_id=-1001,
                text="test",
                category=MessageCategory.HELP_OUTPUT,
            )

        self.assertIs(result, sent)
        bot.send_message.assert_awaited_once_with(-1001, "test")
        create_task_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
