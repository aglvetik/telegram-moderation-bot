from __future__ import annotations

from datetime import datetime, timezone
from html import escape


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return ensure_utc(dt).isoformat()


def from_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    return ensure_utc(datetime.fromisoformat(value))


def escape_html(value: str | None) -> str:
    return escape(value or "")


def build_display_name(first_name: str | None, last_name: str | None = None) -> str:
    parts = [part.strip() for part in (first_name or "", last_name or "") if part and part.strip()]
    return " ".join(parts) if parts else "Пользователь"


def mention_html(user_id: int, display_name: str | None) -> str:
    safe_name = escape_html(display_name or f"ID {user_id}")
    return f'<a href="tg://user?id={user_id}">{safe_name}</a>'


def format_username(username: str | None) -> str:
    if not username:
        return "нет"
    username = username.lstrip("@")
    return f"@{username}"


def russian_plural(value: int, one: str, few: str, many: str) -> str:
    remainder_ten = value % 10
    remainder_hundred = value % 100
    if remainder_ten == 1 and remainder_hundred != 11:
        return one
    if remainder_ten in {2, 3, 4} and remainder_hundred not in {12, 13, 14}:
        return few
    return many


def humanize_duration(seconds: int) -> str:
    if seconds < 60:
        return "меньше минуты"

    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} {russian_plural(minutes, 'минуту', 'минуты', 'минут')}"

    if seconds % (7 * 86400) == 0:
        weeks = seconds // (7 * 86400)
        return f"{weeks} {russian_plural(weeks, 'неделю', 'недели', 'недель')}"

    if seconds % 86400 == 0:
        days = seconds // 86400
        return f"{days} {russian_plural(days, 'день', 'дня', 'дней')}"

    if seconds % 3600 == 0:
        hours = seconds // 3600
        return f"{hours} {russian_plural(hours, 'час', 'часа', 'часов')}"

    rounded_hours = max(1, round(seconds / 3600))
    return f"{rounded_hours} {russian_plural(rounded_hours, 'час', 'часа', 'часов')}"


def format_datetime_ru(dt: datetime | None) -> str:
    if dt is None:
        return "неизвестно"
    local = ensure_utc(dt)
    return local.strftime("%d.%m.%Y %H:%M UTC")
