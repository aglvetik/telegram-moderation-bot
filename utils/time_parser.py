from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta
from typing import Sequence

from utils.constants import MAX_MUTE_DAYS
from utils.exceptions import ValidationError

_COMPACT_SINGLE_CHAR_PATTERN = re.compile(r"^(?P<value>\d+)(?P<unit>[мчдн])$")
_MERGED_DURATION_PATTERN = re.compile(r"^(?P<value>\d+)(?P<unit>[a-zа-яё]+)$", re.IGNORECASE)

_UNIT_ALIASES = {
    "м": ("minutes", True),
    "мин": ("minutes", True),
    "минута": ("minutes", True),
    "минуту": ("minutes", True),
    "минуты": ("minutes", False),
    "минут": ("minutes", False),
    "ч": ("hours", True),
    "час": ("hours", True),
    "часа": ("hours", False),
    "часов": ("hours", False),
    "д": ("days", True),
    "дн": ("days", True),
    "день": ("days", True),
    "дня": ("days", False),
    "дней": ("days", False),
    "н": ("weeks", True),
    "нед": ("weeks", True),
    "неделя": ("weeks", True),
    "неделю": ("weeks", True),
    "недели": ("weeks", False),
    "недель": ("weeks", False),
}


@dataclass(frozen=True, slots=True)
class _DurationComponent:
    duration: timedelta
    consumed: int
    explicit_number: bool


def is_duration_token(token: str) -> bool:
    return _match_duration_component([token], 0) is not None


def parse_duration_token(token: str) -> timedelta:
    component = _match_duration_component([token], 0)
    if component is None or component.consumed != 1:
        raise ValidationError("❌ Неверный формат времени.\nПримеры: 15м, 1ч, 2д")
    return component.duration


def match_duration_tokens(tokens: Sequence[str], start_index: int) -> tuple[timedelta, int] | None:
    first = _match_duration_component(tokens, start_index)
    if first is None:
        return None

    total = first.duration
    consumed = first.consumed

    if not first.explicit_number:
        return _validate_total_duration(total), consumed

    while True:
        next_component = _match_duration_component(tokens, start_index + consumed)
        if next_component is None or not next_component.explicit_number:
            break
        total += next_component.duration
        consumed += next_component.consumed

    return _validate_total_duration(total), consumed


def timedelta_to_seconds(duration: timedelta) -> int:
    return int(duration.total_seconds())


def _match_duration_component(tokens: Sequence[str], start_index: int) -> _DurationComponent | None:
    if start_index >= len(tokens):
        return None

    token = _sanitize_token(tokens[start_index])
    compact_match = _COMPACT_SINGLE_CHAR_PATTERN.fullmatch(token)
    if compact_match:
        duration = _build_duration(int(compact_match.group("value")), compact_match.group("unit"))
        return _DurationComponent(duration=duration, consumed=1, explicit_number=True)

    merged_match = _MERGED_DURATION_PATTERN.fullmatch(token)
    if merged_match:
        normalized_unit = _normalize_unit(merged_match.group("unit"))
        if normalized_unit is not None:
            duration = _build_duration(int(merged_match.group("value")), normalized_unit)
            return _DurationComponent(duration=duration, consumed=1, explicit_number=True)

    if token.isdigit():
        if start_index + 1 >= len(tokens):
            return None
        normalized_unit = _normalize_unit(tokens[start_index + 1])
        if normalized_unit is None:
            return None
        duration = _build_duration(int(token), normalized_unit)
        return _DurationComponent(duration=duration, consumed=2, explicit_number=True)

    normalized_unit = _normalize_unit(token)
    if normalized_unit is None:
        return None

    _, implicit_allowed = _UNIT_ALIASES[_sanitize_token(token)]
    if not implicit_allowed:
        return None

    duration = _build_duration(1, normalized_unit)
    return _DurationComponent(duration=duration, consumed=1, explicit_number=False)


def _normalize_unit(token: str) -> str | None:
    normalized = _sanitize_token(token)
    unit_info = _UNIT_ALIASES.get(normalized)
    if unit_info is None:
        return None

    unit_name = unit_info[0]
    if unit_name == "minutes":
        return "м"
    if unit_name == "hours":
        return "ч"
    if unit_name == "days":
        return "д"
    return "н"


def _sanitize_token(token: str) -> str:
    return token.strip().lower().rstrip(".,;:!?")


def _build_duration(value: int, unit: str) -> timedelta:
    if value <= 0:
        raise ValidationError("❌ Длительность должна быть больше нуля.")

    if unit == "м":
        duration = timedelta(minutes=value)
    elif unit == "ч":
        duration = timedelta(hours=value)
    elif unit == "д":
        duration = timedelta(days=value)
    else:
        duration = timedelta(weeks=value)

    return _validate_total_duration(duration)


def _validate_total_duration(duration: timedelta) -> timedelta:
    if duration > timedelta(days=MAX_MUTE_DAYS):
        raise ValidationError("❌ Максимальная длительность ограничения — 30 дней.")
    return duration
