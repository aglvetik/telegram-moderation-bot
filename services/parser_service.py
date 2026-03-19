from __future__ import annotations

import shlex
from dataclasses import dataclass
from enum import StrEnum

from utils.constants import (
    BOT_COMMAND_ALIASES,
    DEFAULT_MUTE_DURATION_SECONDS,
    MAX_ADMIN_LEVEL,
    MAX_ASSIGNABLE_ADMIN_LEVEL,
    MIN_ADMIN_LEVEL,
)
from utils.exceptions import ParseCommandError
from utils.time_parser import is_duration_token, parse_duration_token, timedelta_to_seconds
from utils.validators import (
    looks_like_username_token,
    normalize_command_text,
    validate_assignable_admin_level,
)


class CommandKind(StrEnum):
    MUTE = "mute"
    UNMUTE = "unmute"
    KICK = "kick"
    BAN = "ban"
    UNBAN = "unban"
    SET_LEVEL = "set_level"
    RAISE_LEVEL = "raise_level"
    LOWER_LEVEL = "lower_level"
    REMOVE_LEVEL = "remove_level"
    VIEW_LEVEL = "view_level"
    MY_LEVEL = "my_level"
    HELP = "help"
    MODERATORS = "moderators"
    INFO = "info"
    HISTORY = "history"
    ACTIVE_MUTES = "active_mutes"


@dataclass(slots=True)
class TargetInput:
    raw: str
    username: str | None = None
    user_id: int | None = None


@dataclass(slots=True)
class ParsedCommand:
    kind: CommandKind
    normalized_text: str
    explicit_target: TargetInput | None = None
    duration_seconds: int | None = None
    reason: str | None = None
    level: int | None = None
    level_delta: int | None = None


class ParserService:
    def parse(self, text: str, *, has_reply: bool) -> ParsedCommand:
        normalized = normalize_command_text(text)
        if not normalized:
            raise ParseCommandError("❌ Не удалось распознать команду.")

        try:
            tokens = shlex.split(normalized, posix=True)
        except ValueError as exc:
            raise ParseCommandError("❌ Не удалось распознать команду.\nПроверьте кавычки и формат сообщения.") from exc

        command = tokens[0].lower()
        arguments = tokens[1:]

        if command in BOT_COMMAND_ALIASES["mute"]:
            return self._parse_mute(arguments, normalized, has_reply=has_reply)
        if command in BOT_COMMAND_ALIASES["unmute"]:
            return self._parse_target_command(
                kind=CommandKind.UNMUTE,
                arguments=arguments,
                normalized=normalized,
                has_reply=has_reply,
                allow_reason=False,
            )
        if command in BOT_COMMAND_ALIASES["kick"]:
            return self._parse_target_command(
                kind=CommandKind.KICK,
                arguments=arguments,
                normalized=normalized,
                has_reply=has_reply,
                allow_reason=True,
            )
        if command in BOT_COMMAND_ALIASES["ban"]:
            return self._parse_target_command(
                kind=CommandKind.BAN,
                arguments=arguments,
                normalized=normalized,
                has_reply=has_reply,
                allow_reason=True,
            )
        if command in BOT_COMMAND_ALIASES["unban"]:
            return self._parse_target_command(
                kind=CommandKind.UNBAN,
                arguments=arguments,
                normalized=normalized,
                has_reply=has_reply,
                allow_reason=False,
            )
        if command in BOT_COMMAND_ALIASES["level"]:
            return self._parse_level(arguments, normalized, has_reply=has_reply)
        if command in BOT_COMMAND_ALIASES["raise_level"]:
            return self._parse_level_mutation(CommandKind.RAISE_LEVEL, arguments, normalized, has_reply=has_reply)
        if command in BOT_COMMAND_ALIASES["lower_level"]:
            return self._parse_level_mutation(CommandKind.LOWER_LEVEL, arguments, normalized, has_reply=has_reply)
        if command in BOT_COMMAND_ALIASES["remove_level"]:
            return self._parse_remove_level(arguments, normalized, has_reply=has_reply)
        if command in BOT_COMMAND_ALIASES["my_level"]:
            return ParsedCommand(kind=CommandKind.MY_LEVEL, normalized_text=normalized)
        if command in BOT_COMMAND_ALIASES["help"]:
            return ParsedCommand(kind=CommandKind.HELP, normalized_text=normalized)
        if command in BOT_COMMAND_ALIASES["moderators"]:
            return ParsedCommand(kind=CommandKind.MODERATORS, normalized_text=normalized)
        if command in BOT_COMMAND_ALIASES["info"]:
            return self._parse_target_command(
                kind=CommandKind.INFO,
                arguments=arguments,
                normalized=normalized,
                has_reply=has_reply,
                allow_reason=False,
            )
        if command in BOT_COMMAND_ALIASES["history"]:
            return self._parse_target_command(
                kind=CommandKind.HISTORY,
                arguments=arguments,
                normalized=normalized,
                has_reply=has_reply,
                allow_reason=False,
            )
        if command in BOT_COMMAND_ALIASES["active_mutes"]:
            return ParsedCommand(kind=CommandKind.ACTIVE_MUTES, normalized_text=normalized)

        raise ParseCommandError("❌ Неизвестная команда.")

    def _parse_mute(self, arguments: list[str], normalized: str, *, has_reply: bool) -> ParsedCommand:
        target_indexes = [index for index, token in enumerate(arguments) if self._looks_like_target(token)]
        duration_indexes = [index for index, token in enumerate(arguments) if is_duration_token(token)]

        if has_reply and target_indexes:
            raise self._invalid_format(
                "Если команда отправлена reply, не указывайте цель повторно.",
                "мут",
                "мут 1ч флуд",
                "мут @username 1ч флуд",
            )
        if len(target_indexes) > 1:
            raise self._ambiguous_target_error()
        if len(duration_indexes) > 1:
            raise self._invalid_format("Укажите только одну длительность мута.", "мут", "мут 1ч флуд", "мут @username 30м спам")
        if not has_reply and not target_indexes:
            raise self._target_required_error()

        explicit_target = self._parse_target(arguments[target_indexes[0]]) if target_indexes else None
        duration_seconds = DEFAULT_MUTE_DURATION_SECONDS
        reserved_indexes = set(target_indexes)

        if duration_indexes:
            reserved_indexes.add(duration_indexes[0])
            duration_seconds = timedelta_to_seconds(parse_duration_token(arguments[duration_indexes[0]]))

        reason_tokens = [token for index, token in enumerate(arguments) if index not in reserved_indexes]
        reason = " ".join(reason_tokens).strip() or None
        return ParsedCommand(
            kind=CommandKind.MUTE,
            normalized_text=normalized,
            explicit_target=explicit_target,
            duration_seconds=duration_seconds,
            reason=reason,
        )

    def _parse_target_command(
        self,
        *,
        kind: CommandKind,
        arguments: list[str],
        normalized: str,
        has_reply: bool,
        allow_reason: bool,
    ) -> ParsedCommand:
        target_indexes = [index for index, token in enumerate(arguments) if self._looks_like_target(token)]
        if has_reply and target_indexes:
            raise self._invalid_format(
                "Если команда отправлена reply, не указывайте цель повторно.",
                self._example_command_for_kind(kind),
            )
        if len(target_indexes) > 1:
            raise self._ambiguous_target_error()
        if not has_reply and not target_indexes:
            raise self._target_required_error()

        reserved_indexes = set(target_indexes)
        reason_tokens = [token for index, token in enumerate(arguments) if index not in reserved_indexes]
        if reason_tokens and not allow_reason:
            raise self._invalid_format(
                "Не удалось безопасно разобрать аргументы команды.",
                self._example_command_for_kind(kind),
            )

        explicit_target = self._parse_target(arguments[target_indexes[0]]) if target_indexes else None
        reason = " ".join(reason_tokens).strip() or None
        return ParsedCommand(kind=kind, normalized_text=normalized, explicit_target=explicit_target, reason=reason)

    def _parse_level(self, arguments: list[str], normalized: str, *, has_reply: bool) -> ParsedCommand:
        target_indexes, level_indexes, unknown_indexes = self._classify_level_arguments(arguments)
        self._ensure_level_arguments_are_safe(
            command_label="уровень",
            arguments=arguments,
            has_reply=has_reply,
            target_indexes=target_indexes,
            level_indexes=level_indexes,
            unknown_indexes=unknown_indexes,
        )

        if has_reply and not arguments:
            return ParsedCommand(kind=CommandKind.VIEW_LEVEL, normalized_text=normalized)
        if has_reply and len(level_indexes) == 1:
            return ParsedCommand(
                kind=CommandKind.SET_LEVEL,
                normalized_text=normalized,
                level=validate_assignable_admin_level(int(arguments[level_indexes[0]])),
            )
        if not has_reply and len(target_indexes) == 1 and not level_indexes:
            return ParsedCommand(
                kind=CommandKind.VIEW_LEVEL,
                normalized_text=normalized,
                explicit_target=self._parse_target(arguments[target_indexes[0]]),
            )
        if not has_reply and len(target_indexes) == 1 and len(level_indexes) == 1:
            return ParsedCommand(
                kind=CommandKind.SET_LEVEL,
                normalized_text=normalized,
                explicit_target=self._parse_target(arguments[target_indexes[0]]),
                level=validate_assignable_admin_level(int(arguments[level_indexes[0]])),
            )
        if not has_reply and not target_indexes and len(level_indexes) == 1:
            raise self._ambiguous_level_or_user_id_error(arguments[level_indexes[0]])

        raise self._invalid_format(
            "Не удалось безопасно определить цель и уровень.",
            "уровень @user 2",
            "уровень 2 @user",
            "уровень @user",
            "уровень 3",
        )

    def _parse_level_mutation(
        self,
        kind: CommandKind,
        arguments: list[str],
        normalized: str,
        *,
        has_reply: bool,
    ) -> ParsedCommand:
        implicit_delta = 1 if kind == CommandKind.RAISE_LEVEL else -1
        target_indexes, level_indexes, unknown_indexes = self._classify_level_arguments(arguments)
        self._ensure_level_arguments_are_safe(
            command_label="повысить" if kind == CommandKind.RAISE_LEVEL else "понизить",
            arguments=arguments,
            has_reply=has_reply,
            target_indexes=target_indexes,
            level_indexes=level_indexes,
            unknown_indexes=unknown_indexes,
        )

        if has_reply and not arguments:
            return ParsedCommand(kind=kind, normalized_text=normalized, level_delta=implicit_delta)
        if has_reply and len(level_indexes) == 1:
            return ParsedCommand(
                kind=kind,
                normalized_text=normalized,
                level=validate_assignable_admin_level(int(arguments[level_indexes[0]])),
            )
        if not has_reply and len(target_indexes) == 1 and not level_indexes:
            return ParsedCommand(
                kind=kind,
                normalized_text=normalized,
                explicit_target=self._parse_target(arguments[target_indexes[0]]),
                level_delta=implicit_delta,
            )
        if not has_reply and len(target_indexes) == 1 and len(level_indexes) == 1:
            return ParsedCommand(
                kind=kind,
                normalized_text=normalized,
                explicit_target=self._parse_target(arguments[target_indexes[0]]),
                level=validate_assignable_admin_level(int(arguments[level_indexes[0]])),
            )
        if not has_reply and not target_indexes and len(level_indexes) == 1:
            raise self._ambiguous_level_or_user_id_error(arguments[level_indexes[0]])

        command = "повысить" if kind == CommandKind.RAISE_LEVEL else "понизить"
        raise self._invalid_format(
            "Не удалось безопасно определить цель и новый уровень.",
            command,
            f"{command} @user",
            f"{command} @user 3" if kind == CommandKind.RAISE_LEVEL else f"{command} @user 1",
            f"{command} 3 @user" if kind == CommandKind.RAISE_LEVEL else f"{command} 1 @user",
        )

    def _parse_remove_level(self, arguments: list[str], normalized: str, *, has_reply: bool) -> ParsedCommand:
        target_indexes = [index for index, token in enumerate(arguments) if self._looks_like_target(token)]
        if has_reply and not arguments:
            return ParsedCommand(kind=CommandKind.REMOVE_LEVEL, normalized_text=normalized)
        if has_reply and arguments:
            raise self._invalid_format(
                "Если команда отправлена reply, не указывайте цель повторно.",
                "снятьуровень",
                "снятьуровень @user",
            )
        if len(target_indexes) != 1 or len(arguments) != 1:
            raise self._invalid_format("Не удалось безопасно определить пользователя.", "снятьуровень", "снятьуровень @user")
        return ParsedCommand(
            kind=CommandKind.REMOVE_LEVEL,
            normalized_text=normalized,
            explicit_target=self._parse_target(arguments[target_indexes[0]]),
        )

    def _classify_level_arguments(self, arguments: list[str]) -> tuple[list[int], list[int], list[int]]:
        target_indexes: list[int] = []
        level_indexes: list[int] = []
        unknown_indexes: list[int] = []

        for index, token in enumerate(arguments):
            stripped = token.strip()
            if stripped.isdigit():
                value = int(stripped)
                if MIN_ADMIN_LEVEL <= value <= MAX_ADMIN_LEVEL:
                    level_indexes.append(index)
                else:
                    target_indexes.append(index)
                continue
            if self._looks_like_target(stripped):
                target_indexes.append(index)
                continue
            unknown_indexes.append(index)

        return target_indexes, level_indexes, unknown_indexes

    def _ensure_level_arguments_are_safe(
        self,
        *,
        command_label: str,
        arguments: list[str],
        has_reply: bool,
        target_indexes: list[int],
        level_indexes: list[int],
        unknown_indexes: list[int],
    ) -> None:
        if unknown_indexes:
            raise self._invalid_format(
                "Команда содержит лишние или непонятные аргументы.",
                command_label,
                f"{command_label} @user 2",
                f"{command_label} 2 @user",
            )
        if len(target_indexes) > 1:
            raise self._ambiguous_target_error()
        if len(level_indexes) > 1:
            raise self._invalid_format(
                "Укажите только один итоговый уровень.",
                command_label,
                f"{command_label} @user 2",
                f"{command_label} 2 @user",
            )
        if has_reply and target_indexes:
            raise self._invalid_format(
                "Если команда отправлена reply, не указывайте цель повторно.",
                command_label,
                f"{command_label} 2",
            )

    @staticmethod
    def _looks_like_target(token: str) -> bool:
        stripped = token.strip()
        return stripped.isdigit() or stripped.startswith("@") or looks_like_username_token(stripped)

    @staticmethod
    def _parse_target(token: str) -> TargetInput:
        stripped = token.strip()
        if stripped.isdigit():
            return TargetInput(raw=stripped, user_id=int(stripped))
        if stripped.startswith("@") or looks_like_username_token(stripped):
            username = stripped.lstrip("@")
            return TargetInput(raw=stripped, username=username)
        raise ParseCommandError("❌ Неверный идентификатор пользователя.")

    @staticmethod
    def _target_required_error() -> ParseCommandError:
        return ParseCommandError("❌ Не удалось определить пользователя.\nИспользуйте reply, username или user_id.")

    @staticmethod
    def _ambiguous_target_error() -> ParseCommandError:
        return ParseCommandError(
            "❌ Команда содержит несколько возможных целей.\n"
            "Укажите только одного пользователя через reply, username или user_id."
        )

    @staticmethod
    def _ambiguous_level_or_user_id_error(token: str) -> ParseCommandError:
        return ParseCommandError(
            "❌ Команда получилась неоднозначной.\n"
            f"Число <code>{token}</code> может означать и уровень, и user_id.\n"
            "Укажите цель явно через reply, @username или полный user_id рядом с уровнем."
        )

    @staticmethod
    def _invalid_format(summary: str, *examples: str) -> ParseCommandError:
        lines = [f"❌ Неверный формат команды.\n{summary}"]
        if examples:
            lines.append("Примеры:")
            lines.extend(examples)
        return ParseCommandError("\n".join(lines))

    @staticmethod
    def _example_command_for_kind(kind: CommandKind) -> str:
        examples = {
            CommandKind.UNMUTE: "анмут @user",
            CommandKind.KICK: "кик @user",
            CommandKind.BAN: "бан @user причина",
            CommandKind.UNBAN: "разбан @user",
            CommandKind.INFO: "инфо @user",
            CommandKind.HISTORY: "история @user",
        }
        return examples.get(kind, kind.value)
