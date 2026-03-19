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
from utils.time_parser import match_duration_tokens, timedelta_to_seconds
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
                allow_duration=False,
            )
        if command in BOT_COMMAND_ALIASES["kick"]:
            return self._parse_target_command(
                kind=CommandKind.KICK,
                arguments=arguments,
                normalized=normalized,
                has_reply=has_reply,
                allow_reason=True,
                allow_duration=False,
            )
        if command in BOT_COMMAND_ALIASES["ban"]:
            return self._parse_target_command(
                kind=CommandKind.BAN,
                arguments=arguments,
                normalized=normalized,
                has_reply=has_reply,
                allow_reason=True,
                allow_duration=True,
            )
        if command in BOT_COMMAND_ALIASES["unban"]:
            return self._parse_target_command(
                kind=CommandKind.UNBAN,
                arguments=arguments,
                normalized=normalized,
                has_reply=has_reply,
                allow_reason=False,
                allow_duration=False,
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
                allow_duration=False,
            )
        if command in BOT_COMMAND_ALIASES["history"]:
            return self._parse_target_command(
                kind=CommandKind.HISTORY,
                arguments=arguments,
                normalized=normalized,
                has_reply=has_reply,
                allow_reason=False,
                allow_duration=False,
            )
        if command in BOT_COMMAND_ALIASES["active_mutes"]:
            return ParsedCommand(kind=CommandKind.ACTIVE_MUTES, normalized_text=normalized)

        raise ParseCommandError("❌ Неизвестная команда.")

    def _parse_mute(self, arguments: list[str], normalized: str, *, has_reply: bool) -> ParsedCommand:
        duration_seconds, reserved_indexes = self._extract_optional_duration(
            arguments,
            summary="Укажите только одну длительность мута.",
            examples=("мут 1ч флуд", "мут 30 минут @user"),
        )
        explicit_target, reserved_indexes = self._extract_optional_target(
            arguments,
            reserved_indexes=reserved_indexes,
            has_reply=has_reply,
            allow_reason=True,
            command_examples=("мут 1ч флуд", "мут @username 30 минут флуд", "мут 30 минут @username"),
        )
        if not has_reply and explicit_target is None:
            raise self._target_required_error()

        reason = self._build_reason(arguments, reserved_indexes)
        return ParsedCommand(
            kind=CommandKind.MUTE,
            normalized_text=normalized,
            explicit_target=explicit_target,
            duration_seconds=duration_seconds or DEFAULT_MUTE_DURATION_SECONDS,
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
        allow_duration: bool,
    ) -> ParsedCommand:
        reserved_indexes: set[int] = set()
        duration_seconds: int | None = None

        if allow_duration:
            duration_seconds, reserved_indexes = self._extract_optional_duration(
                arguments,
                summary="Укажите только одну длительность бана.",
                examples=("бан @user 1 день", "бан 2 часа @user спам"),
            )

        explicit_target, reserved_indexes = self._extract_optional_target(
            arguments,
            reserved_indexes=reserved_indexes,
            has_reply=has_reply,
            allow_reason=allow_reason,
            command_examples=(self._example_command_for_kind(kind),),
        )
        if not has_reply and explicit_target is None:
            raise self._target_required_error()

        reason = self._build_reason(arguments, reserved_indexes)
        if reason and not allow_reason:
            raise self._invalid_format(
                "Не удалось безопасно разобрать аргументы команды.",
                self._example_command_for_kind(kind),
            )

        return ParsedCommand(
            kind=kind,
            normalized_text=normalized,
            explicit_target=explicit_target,
            duration_seconds=duration_seconds,
            reason=reason,
        )

    def _parse_level(self, arguments: list[str], normalized: str, *, has_reply: bool) -> ParsedCommand:
        target_indexes, level_indexes, unknown_indexes = self._classify_level_arguments(arguments)
        self._ensure_level_arguments_are_safe(
            command_label="уровень",
            target_indexes=target_indexes,
            level_indexes=level_indexes,
            unknown_indexes=unknown_indexes,
        )

        explicit_target = self._parse_target(arguments[target_indexes[0]]) if target_indexes else None
        explicit_level = validate_assignable_admin_level(int(arguments[level_indexes[0]])) if level_indexes else None

        if has_reply:
            if explicit_level is None:
                return ParsedCommand(
                    kind=CommandKind.VIEW_LEVEL,
                    normalized_text=normalized,
                    explicit_target=explicit_target,
                )
            return ParsedCommand(
                kind=CommandKind.SET_LEVEL,
                normalized_text=normalized,
                explicit_target=explicit_target,
                level=explicit_level,
            )

        if explicit_target and explicit_level is None:
            return ParsedCommand(
                kind=CommandKind.VIEW_LEVEL,
                normalized_text=normalized,
                explicit_target=explicit_target,
            )
        if explicit_target and explicit_level is not None:
            return ParsedCommand(
                kind=CommandKind.SET_LEVEL,
                normalized_text=normalized,
                explicit_target=explicit_target,
                level=explicit_level,
            )
        if explicit_level is not None:
            raise self._ambiguous_level_or_user_id_error(arguments[level_indexes[0]])

        raise self._invalid_format(
            "Не удалось безопасно определить цель и уровень.",
            "уровень @user",
            "уровень @user 2",
            "уровень 2 @user",
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
        command_label = "повысить" if kind == CommandKind.RAISE_LEVEL else "понизить"

        target_indexes, level_indexes, unknown_indexes = self._classify_level_arguments(arguments)
        self._ensure_level_arguments_are_safe(
            command_label=command_label,
            target_indexes=target_indexes,
            level_indexes=level_indexes,
            unknown_indexes=unknown_indexes,
        )

        explicit_target = self._parse_target(arguments[target_indexes[0]]) if target_indexes else None
        explicit_level = validate_assignable_admin_level(int(arguments[level_indexes[0]])) if level_indexes else None

        if has_reply:
            if explicit_level is not None:
                return ParsedCommand(
                    kind=kind,
                    normalized_text=normalized,
                    explicit_target=explicit_target,
                    level=explicit_level,
                )
            if explicit_target is not None or not arguments:
                return ParsedCommand(
                    kind=kind,
                    normalized_text=normalized,
                    explicit_target=explicit_target,
                    level_delta=implicit_delta,
                )

        if explicit_target and explicit_level is None:
            return ParsedCommand(
                kind=kind,
                normalized_text=normalized,
                explicit_target=explicit_target,
                level_delta=implicit_delta,
            )
        if explicit_target and explicit_level is not None:
            return ParsedCommand(
                kind=kind,
                normalized_text=normalized,
                explicit_target=explicit_target,
                level=explicit_level,
            )
        if explicit_level is not None:
            raise self._ambiguous_level_or_user_id_error(arguments[level_indexes[0]])

        raise self._invalid_format(
            "Не удалось безопасно определить цель и новый уровень.",
            command_label,
            f"{command_label} @user",
            f"{command_label} @user 3" if kind == CommandKind.RAISE_LEVEL else f"{command_label} @user 1",
            f"{command_label} 3 @user" if kind == CommandKind.RAISE_LEVEL else f"{command_label} 1 @user",
        )

    def _parse_remove_level(self, arguments: list[str], normalized: str, *, has_reply: bool) -> ParsedCommand:
        target_indexes = [index for index, token in enumerate(arguments) if self._looks_like_target(token)]
        if len(target_indexes) > 1:
            raise self._ambiguous_target_error()
        if len(target_indexes) == 1 and len(arguments) != 1:
            raise self._invalid_format("Не удалось безопасно определить пользователя.", "снятьуровень", "снятьуровень @user")
        if not has_reply and len(target_indexes) != 1:
            raise self._invalid_format("Не удалось безопасно определить пользователя.", "снятьуровень @user")
        if has_reply and not arguments:
            return ParsedCommand(kind=CommandKind.REMOVE_LEVEL, normalized_text=normalized)
        if target_indexes:
            return ParsedCommand(
                kind=CommandKind.REMOVE_LEVEL,
                normalized_text=normalized,
                explicit_target=self._parse_target(arguments[target_indexes[0]]),
            )
        raise self._invalid_format("Не удалось безопасно определить пользователя.", "снятьуровень", "снятьуровень @user")

    def _extract_optional_duration(
        self,
        arguments: list[str],
        *,
        summary: str,
        examples: tuple[str, ...],
    ) -> tuple[int | None, set[int]]:
        found_seconds: int | None = None
        reserved_indexes: set[int] = set()
        index = 0

        while index < len(arguments):
            match = match_duration_tokens(arguments, index)
            if match is None:
                index += 1
                continue

            duration, consumed = match
            if any((index + offset) in reserved_indexes for offset in range(consumed)):
                index += 1
                continue
            if found_seconds is not None:
                raise self._invalid_format(summary, *examples)

            found_seconds = timedelta_to_seconds(duration)
            for offset in range(consumed):
                reserved_indexes.add(index + offset)
            index += consumed

        return found_seconds, reserved_indexes

    def _extract_optional_target(
        self,
        arguments: list[str],
        *,
        reserved_indexes: set[int],
        has_reply: bool,
        allow_reason: bool,
        command_examples: tuple[str, ...],
    ) -> tuple[TargetInput | None, set[int]]:
        explicit_indexes = [
            index
            for index, token in enumerate(arguments)
            if index not in reserved_indexes and self._is_explicit_target_marker(token)
        ]
        if len(explicit_indexes) > 1:
            raise self._ambiguous_target_error()

        target_index: int | None = None
        if len(explicit_indexes) == 1:
            target_index = explicit_indexes[0]
        else:
            bare_indexes = [
                index
                for index, token in enumerate(arguments)
                if index not in reserved_indexes and looks_like_username_token(token.strip())
            ]
            if len(bare_indexes) > 1:
                raise self._ambiguous_target_error()
            if len(bare_indexes) == 1:
                remaining_indexes = [index for index in range(len(arguments)) if index not in reserved_indexes]
                if not has_reply and allow_reason and remaining_indexes == bare_indexes:
                    raise self._invalid_format(
                        "Не удалось безопасно понять, указан ли username или свободный текст.",
                        *command_examples,
                    )
                target_index = bare_indexes[0]

        if target_index is None:
            return None, reserved_indexes

        updated_reserved = set(reserved_indexes)
        updated_reserved.add(target_index)
        return self._parse_target(arguments[target_index]), updated_reserved

    @staticmethod
    def _build_reason(arguments: list[str], reserved_indexes: set[int]) -> str | None:
        reason_tokens = [token for index, token in enumerate(arguments) if index not in reserved_indexes]
        reason = " ".join(reason_tokens).strip()
        return reason or None

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

    @staticmethod
    def _looks_like_target(token: str) -> bool:
        stripped = token.strip()
        return stripped.isdigit() or stripped.startswith("@") or looks_like_username_token(stripped)

    @staticmethod
    def _is_explicit_target_marker(token: str) -> bool:
        stripped = token.strip()
        return stripped.isdigit() or stripped.startswith("@")

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
        return ParseCommandError(
            "❌ Не удалось определить пользователя.\n"
            "Укажите цель одним из способов:\n"
            "• ответом на сообщение\n"
            "• username\n"
            "• user_id"
        )

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
            CommandKind.KICK: "кик @user причина",
            CommandKind.BAN: "бан @user 1 день причина",
            CommandKind.UNBAN: "разбан @user",
            CommandKind.INFO: "инфо @user",
            CommandKind.HISTORY: "история @user",
        }
        return examples.get(kind, kind.value)
