from __future__ import annotations

import re
from datetime import timedelta

from utils.constants import MAX_MUTE_DAYS
from utils.exceptions import ValidationError

_DURATION_PATTERN = re.compile(r"^(?P<value>\d+)(?P<unit>[мчдн])$")


def is_duration_token(token: str) -> bool:
    return bool(_DURATION_PATTERN.fullmatch(token.strip().lower()))


def parse_duration_token(token: str) -> timedelta:
    token = token.strip().lower()
    match = _DURATION_PATTERN.fullmatch(token)
    if not match:
        raise ValidationError("❌ Неверный формат времени.\nПримеры: 15м, 1ч, 2д")

    value = int(match.group("value"))
    unit = match.group("unit")
    if value <= 0:
        raise ValidationError("❌ Длительность мута должна быть больше нуля.")

    if unit == "м":
        duration = timedelta(minutes=value)
    elif unit == "ч":
        duration = timedelta(hours=value)
    elif unit == "д":
        duration = timedelta(days=value)
    else:
        duration = timedelta(weeks=value)

    if duration > timedelta(days=MAX_MUTE_DAYS):
        raise ValidationError("❌ Максимальная длительность мута — 30 дней.")
    return duration


def timedelta_to_seconds(duration: timedelta) -> int:
    return int(duration.total_seconds())
