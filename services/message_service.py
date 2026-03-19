from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from aiogram import Bot
from aiogram.types import Message

from config import AppConfig
from database.models import ActiveMuteRecord, PunishmentRecord
from services.user_resolution_service import ResolvedUser
from utils.constants import (
    AUTO_DELETE_MESSAGE_CATEGORIES,
    DEFAULT_REASON,
    HISTORY_ACTION_LABELS,
    MessageCategory,
    PERSISTENT_MESSAGE_CATEGORIES,
)
from utils.formatters import format_datetime_ru, format_username, humanize_duration, mention_html
from utils.telegram_helpers import delete_message_later


class MessageService:
    """Generates user-facing texts and applies the centralized bot message deletion policy."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.logger = logging.getLogger(__name__)

    async def reply(
        self,
        *,
        bot: Bot,
        message: Message,
        text: str,
        category: MessageCategory,
    ) -> Message:
        sent = await message.answer(text)
        self._schedule_auto_delete(bot=bot, message=sent, category=category)
        return sent

    async def send_to_chat(
        self,
        *,
        bot: Bot,
        chat_id: int,
        text: str,
        category: MessageCategory,
    ) -> Message:
        sent = await bot.send_message(chat_id, text)
        self._schedule_auto_delete(bot=bot, message=sent, category=category)
        return sent

    async def maybe_delete_command(self, *, bot: Bot, message: Message) -> None:
        if not self.config.message_policy.delete_command_messages:
            return
        asyncio.create_task(
            delete_message_later(
                bot,
                message,
                delay_seconds=self.config.message_policy.command_delete_delay_seconds,
                logger=self.logger,
            )
        )

    def delete_delay_for_category(self, category: MessageCategory) -> int | None:
        if category in PERSISTENT_MESSAGE_CATEGORIES:
            return None
        if category in AUTO_DELETE_MESSAGE_CATEGORIES:
            return self.config.message_policy.ordinary_message_delete_seconds
        self.logger.debug("Unknown message category %s; using ordinary auto-delete policy", category)
        return self.config.message_policy.ordinary_message_delete_seconds

    def _schedule_auto_delete(self, *, bot: Bot, message: Message, category: MessageCategory) -> None:
        delay_seconds = self.delete_delay_for_category(category)
        if delay_seconds is None or delay_seconds <= 0:
            return
        asyncio.create_task(
            delete_message_later(
                bot,
                message,
                delay_seconds=delay_seconds,
                logger=self.logger,
            )
        )

    def private_start(self) -> str:
        return (
            "🤖 <b>Привет! Я — бот модерации для Telegram-групп.</b>\n\n"
            "Я помогаю наводить порядок в чате и поддерживаю удобную систему внутренних уровней модерации.\n\n"
            "<b>Что я умею:</b>\n"
            "• выдавать мут и снимать его\n"
            "• исключать пользователей из чата\n"
            "• банить и разбанивать\n"
            "• работать по reply, username и user_id — там, где это позволяет Telegram\n"
            "• учитывать внутренние уровни доступа модераторов\n\n"
            "<b>Где я работаю:</b>\n"
            "Команды модерации доступны в <b>группах и супергруппах</b>.\n"
            "В личных сообщениях я могу только рассказать о себе и подсказать, как начать работу.\n\n"
            "<b>Как начать:</b>\n"
            "1. Добавьте меня в группу\n"
            "2. Выдайте мне права администратора\n"
            "3. Используйте команду <code>помощь</code>, чтобы посмотреть доступные действия\n\n"
            "<b>Важно:</b>\n"
            "Некоторые функции Telegram зависят от ограничений Bot API, поэтому поиск по username работает только там, "
            "где пользователь уже известен боту.\n\n"
            "Готов к работе. Добавьте меня в чат, и я помогу с модерацией."
        )

    def welcome_group(self) -> str:
        return (
            "👋 <b>Всем привет! Я — бот модерации и уже готов к работе.</b>\n\n"
            "Я помогаю управлять чатом, поддерживать порядок и использовать внутреннюю систему уровней модерации.\n\n"
            "<b>Основные возможности:</b>\n"
            "• 🔇 мут и снятие мута\n"
            "• 👢 исключение пользователей\n"
            "• ⛔ бан и разбан\n"
            "• 🛡 внутренняя система прав модераторов\n\n"
            "<b>Поддерживаемые способы указания пользователя:</b>\n"
            "• ответом на сообщение\n"
            "• по username\n"
            "• по user_id\n\n"
            "<b>Примеры команд:</b>\n"
            "<code>мут 1ч флуд</code>\n"
            "<code>мут @username 30м спам</code>\n"
            "<code>анмут @username</code>\n"
            "<code>кик @username</code>\n"
            "<code>бан @username</code>\n"
            "<code>разбан 123456789</code>\n\n"
            "<b>Важно для корректной работы:</b>\n"
            "Мне нужны права администратора в этом чате.\n"
            "Часть возможностей Telegram зависит от ограничений Bot API, поэтому некоторые действия по username работают "
            "только если пользователь уже известен боту.\n\n"
            "Напишите <code>помощь</code>, чтобы посмотреть доступные команды."
        )

    def welcome_channel(self) -> str:
        return (
            "ℹ️ <b>Я добавлен в канал.</b>\n\n"
            "Команды модерации пользователей работают только в <b>группах и супергруппах</b>.\n"
            "Если вы хотите использовать функции мута, кика, бана и системы уровней, добавьте меня именно в групповой чат."
        )

    def moderation_groups_only(self) -> str:
        return "ℹ️ Эта команда работает только в группах и супергруппах."

    def moderation_channels_only(self) -> str:
        return "ℹ️ Команды модерации пользователей недоступны в каналах."

    def insufficient_level(self, required_level: int) -> str:
        return (
            "❌ <b>Недостаточно прав для выполнения команды.</b>\n"
            f"Требуемый уровень модерации: <b>{required_level}</b>"
        )

    def caller_not_member(self) -> str:
        return (
            "❌ <b>Команда недоступна.</b>\n"
            "Похоже, вы больше не состоите в этом чате."
        )

    def bot_lacks_rights(self) -> str:
        return (
            "❌ <b>Боту не хватает прав для выполнения этого действия.</b>\n\n"
            "Выдайте боту необходимые права администратора."
        )

    def target_not_found(self) -> str:
        return (
            "❌ <b>Не удалось определить пользователя.</b>\n\n"
            "Укажите цель одним из способов:\n"
            "• ответом на сообщение\n"
            "• username\n"
            "• user_id"
        )

    def conflicting_targets(self) -> str:
        return (
            "❌ Обнаружены две разные цели команды.\n"
            "Если вы отвечаете на сообщение, бот использует автора этого сообщения.\n"
            "Уберите лишний username/user_id или оставьте только одну цель."
        )

    def username_resolution_failed(self) -> str:
        return (
            "❌ <b>Пользователь по указанному username не найден.</b>\n\n"
            "Возможно, он ещё не взаимодействовал с ботом в этом чате.\n"
            "Попробуйте использовать reply или user_id."
        )

    def target_is_bot(self) -> str:
        return "❌ Нельзя применять это действие к самому боту."

    def target_is_self(self) -> str:
        return "❌ Нельзя применять это действие к самому себе."

    def target_is_owner(self) -> str:
        return "❌ <b>Нельзя применить действие.</b>\nВладелец чата защищён от санкций."

    def target_higher_level(self) -> str:
        return (
            "❌ <b>Нельзя применить действие.</b>\n"
            "У пользователя более высокий уровень модерации."
        )

    def target_equal_level(self) -> str:
        return "❌ Нельзя применять действие к пользователю с таким же уровнем модерации."

    def target_admin_protected(self) -> str:
        return (
            "❌ Невозможно выполнить действие.\n"
            "Этот пользователь является администратором."
        )

    def target_unavailable(self) -> str:
        return (
            "❌ <b>Не удалось выполнить действие.</b>\n\n"
            "Пользователь недоступен для бота в этом чате."
        )

    def generic_action_failed(self) -> str:
        return (
            "❌ <b>Не удалось выполнить действие.</b>\n\n"
            "Возможно:\n"
            "• у бота недостаточно прав\n"
            "• пользователь имеет более высокий статус\n"
            "• Telegram ограничил выполнение операции"
        )

    def internal_error(self) -> str:
        return (
            "❌ <b>Произошла внутренняя ошибка.</b>\n"
            "Попробуйте повторить действие чуть позже."
        )

    def level_five_reserved(self) -> str:
        return (
            "❌ <b>Уровень 5 недоступен для назначения командами.</b>\n"
            "Он зарезервирован за системным владельцем бота."
        )

    def level_assignment_cap(self, max_level: int) -> str:
        return (
            "❌ <b>Нельзя назначить указанный уровень.</b>\n"
            f"С вашим уровнем доступа можно выдавать уровни только до <b>{max_level}</b>."
        )

    def level_already_max_assignable(self, max_level: int = 4) -> str:
        return (
            "⚠️ <b>Повысить уровень больше нельзя.</b>\n"
            f"Пользователь уже находится на максимальном доступном уровне <b>{max_level}</b>."
        )

    def level_already_min(self) -> str:
        return (
            "⚠️ <b>Уровень уже минимальный.</b>\n"
            "Ниже <b>0</b> опустить нельзя."
        )

    def already_banned(self) -> str:
        return "⚠️ <b>Пользователь уже находится в чёрном списке.</b>"

    def user_link(self, user: ResolvedUser) -> str:
        return mention_html(user.user_id, user.display_name)

    def mute_success(self, target: ResolvedUser, moderator: ResolvedUser, duration_seconds: int, reason: str) -> str:
        return (
            f"🔇 Пользователь {self.user_link(target)} лишается права слова на {humanize_duration(duration_seconds)}.\n"
            f"💬 Причина: {reason}\n"
            f"👺 Модератор: {self.user_link(moderator)}"
        )

    def mute_already_active(self, target: ResolvedUser, remaining_seconds: int) -> str:
        return (
            f"⚠️ Пользователь {self.user_link(target)} уже находится в муте.\n"
            f"Ограничение действует ещё {humanize_duration(max(remaining_seconds, 60))}."
        )

    def unmute_success(self, target: ResolvedUser) -> str:
        return (
            f"✅ Пользователю {self.user_link(target)} вернули право слова.\n"
            "Снова можно общаться свободно."
        )

    def kick_success(self, target: ResolvedUser, moderator: ResolvedUser) -> str:
        return (
            f"👢 Пользователь {self.user_link(target)} был удалён из беседы.\n"
            f"👺 Модератор: {self.user_link(moderator)}"
        )

    def ban_success(self, target: ResolvedUser, moderator: ResolvedUser) -> str:
        return (
            f"⛔ Пользователь {self.user_link(target)} забанен и отправлен в чёрный список.\n"
            f"👺 Модератор: {self.user_link(moderator)}"
        )

    def unban_success(self, target: ResolvedUser) -> str:
        return (
            f"✅ Пользователь {self.user_link(target)} удалён из чёрного списка.\n"
            "Теперь он может снова присоединиться к чату."
        )

    def level_assigned(self, target: ResolvedUser, level: int) -> str:
        return f"🛡 Пользователю {self.user_link(target)} назначен уровень модерации <b>{level}</b>."

    def level_removed(self, target: ResolvedUser) -> str:
        return f"✅ У пользователя {self.user_link(target)} снят внутренний уровень модерации."

    def level_info(self, target: ResolvedUser, level: int) -> str:
        del target
        return f"ℹ️ <b>Уровень модерации пользователя:</b> {level}"

    def my_level(self, level: int) -> str:
        return (
            f"ℹ️ <b>Ваш уровень модерации:</b> {level}\n\n"
            "Чем выше уровень, тем больше доступных возможностей управления чатом."
        )

    def moderators_list(self, rows: list[tuple[ResolvedUser, int]]) -> str:
        if not rows:
            return "ℹ️ В этом чате пока нет назначенных модераторов."
        lines = ["🛡 <b>Список модераторов чата:</b>", ""]
        for user, level in rows:
            lines.append(f"• {self.user_link(user)} — уровень <b>{level}</b>")
        return "\n".join(lines)

    def help_message(self, caller_level: int, *, private_chat: bool = False) -> str:
        if private_chat:
            return (
                "ℹ️ <b>Справка по командам бота</b>\n\n"
                "Команды модерации работают только в <b>группах и супергруппах</b>.\n"
                "В личных сообщениях я могу только рассказать о себе и подсказать, как начать работу."
            )

        lines = [
            "ℹ️ <b>Справка по командам бота</b>",
            "",
            "Этот бот помогает поддерживать порядок в чате и использует внутреннюю систему уровней модерации.",
            "",
            "<b>Основные команды:</b>",
            "• <code>помощь</code> / <code>help</code> / <code>команды</code> — показать эту справку",
            "• <code>мойуровень</code> — узнать свой уровень модерации",
        ]

        if caller_level >= 2:
            lines.extend(
                [
                    "",
                    "<b>Информация:</b>",
                    "• <code>уровень @user</code> — посмотреть уровень пользователя",
                    "• <code>инфо @user</code> — информация о пользователе",
                    "• <code>история @user</code> — история действий модерации",
                    "• <code>муты</code> — список активных мутов",
                    "",
                    "<b>Модерация (в зависимости от уровня):</b>",
                    "• <code>мут</code> / <code>м</code> — выдать мут",
                    "• <code>анмут</code> — снять мут",
                ]
            )
            if caller_level >= 3:
                lines.append("• <code>кик</code> — удалить пользователя из чата")
            if caller_level >= 4:
                lines.extend(
                    [
                        "• <code>бан</code> — заблокировать пользователя",
                        "• <code>разбан</code> — снять бан",
                        "",
                        "<b>Управление уровнями:</b>",
                        "• <code>повысить</code>",
                        "• <code>понизить</code>",
                        "• <code>снятьуровень</code>",
                        "• <code>модеры</code> / <code>списокмодеров</code>",
                    ]
                )

        lines.extend(
            [
                "",
                "<b>Подсказки:</b>",
                "Самый надёжный способ указать пользователя — ответить на его сообщение.",
                "",
                "Также можно использовать:",
                "• username",
                "• user_id",
            ]
        )
        return "\n".join(lines)

    def help_unavailable_for_level_zero(self) -> str:
        return (
            "ℹ️ Полная справка по модерации доступна только назначенным модераторам.\n"
            "Если вам нужна работа с командами бота, обратитесь к администрации чата."
        )

    def user_info(
        self,
        target: ResolvedUser,
        *,
        level: int,
        active_mute: ActiveMuteRecord | None,
        active_ban: bool,
    ) -> str:
        lines = [
            "ℹ️ <b>Информация о пользователе</b>",
            "",
            f"👤 Пользователь: {self.user_link(target)}",
            "",
            f"ID: <code>{target.user_id}</code>",
            f"Username: {format_username(target.username)}",
            "",
            f"🛡 Уровень модерации: {level}",
            f"⛔ Активный бан: {'да' if active_ban else 'нет'}",
        ]
        if active_mute:
            remaining = max(int((active_mute.ends_at - datetime.now(active_mute.ends_at.tzinfo)).total_seconds()), 0)
            lines.extend(
                [
                    "",
                    f"🔇 Мут действует ещё: {humanize_duration(max(remaining, 60))}",
                ]
            )
        return "\n".join(lines)

    def history(self, target: ResolvedUser, records: list[PunishmentRecord]) -> str:
        lines = [
            "📚 <b>История модерации пользователя</b>",
            "",
            "Далее перечисляются последние действия модераторов.",
        ]
        if not records:
            lines.extend(
                [
                    "",
                    f"Пользователь: {self.user_link(target)}",
                    "Записей пока нет.",
                ]
            )
            return "\n".join(lines)

        lines.extend(["", f"Пользователь: {self.user_link(target)}"])
        for record in records:
            label = HISTORY_ACTION_LABELS.get(record.action_type, record.action_type)
            reason = record.reason or DEFAULT_REASON
            suffix = ""
            if record.duration_seconds:
                suffix = f" • срок: {humanize_duration(record.duration_seconds)}"
            lines.append(f"• {label} — {reason}{suffix} • {format_datetime_ru(record.created_at)}")
        return "\n".join(lines)

    def active_mutes(self, items: list[tuple[ResolvedUser, ActiveMuteRecord]]) -> str:
        if not items:
            return "ℹ️ Сейчас в этом чате нет активных мутов."

        lines = [
            "🔇 <b>Активные муты в чате:</b>",
            "",
            "Далее список пользователей с оставшимся временем мута.",
        ]
        for user, mute in items:
            remaining = max(int((mute.ends_at - datetime.now(mute.ends_at.tzinfo)).total_seconds()), 0)
            lines.append(f"• {self.user_link(user)} — ещё {humanize_duration(max(remaining, 60))}")
        return "\n".join(lines)
