from __future__ import annotations

import unittest

from services.parser_service import CommandKind, ParserService
from utils.exceptions import ParseCommandError, ValidationError


class ParserServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = ParserService()

    def test_parse_default_mute_by_reply_without_duration(self) -> None:
        parsed = self.parser.parse("мут", has_reply=True)
        self.assertEqual(parsed.kind, CommandKind.MUTE)
        self.assertEqual(parsed.duration_seconds, 3600)
        self.assertIsNone(parsed.reason)
        self.assertIsNone(parsed.explicit_target)

    def test_parse_default_mute_by_username_without_duration(self) -> None:
        parsed = self.parser.parse("мут @User", has_reply=False)
        self.assertEqual(parsed.kind, CommandKind.MUTE)
        self.assertEqual(parsed.explicit_target.username, "User")
        self.assertEqual(parsed.duration_seconds, 3600)
        self.assertIsNone(parsed.reason)

    def test_parse_reply_mute_with_implicit_hour(self) -> None:
        parsed = self.parser.parse("мут час", has_reply=True)
        self.assertEqual(parsed.duration_seconds, 3600)
        self.assertIsNone(parsed.reason)

    def test_parse_reply_mute_with_implicit_week(self) -> None:
        parsed = self.parser.parse("мут неделя", has_reply=True)
        self.assertEqual(parsed.duration_seconds, 7 * 86400)

    def test_parse_reply_mute_with_implicit_minute_accusative(self) -> None:
        parsed = self.parser.parse("мут минуту флуд", has_reply=True)
        self.assertEqual(parsed.duration_seconds, 60)
        self.assertEqual(parsed.reason, "флуд")

    def test_parse_reply_mute_with_split_duration(self) -> None:
        parsed = self.parser.parse("мут 30 минут", has_reply=True)
        self.assertEqual(parsed.kind, CommandKind.MUTE)
        self.assertEqual(parsed.duration_seconds, 1800)
        self.assertIsNone(parsed.reason)

    def test_parse_reply_mute_with_duration_and_reason(self) -> None:
        parsed = self.parser.parse("мут 30 минут флуд", has_reply=True)
        self.assertEqual(parsed.duration_seconds, 1800)
        self.assertEqual(parsed.reason, "флуд")

    def test_parse_reply_mute_with_reason_before_duration(self) -> None:
        parsed = self.parser.parse("мут флуд 30 минут", has_reply=True)
        self.assertEqual(parsed.duration_seconds, 1800)
        self.assertEqual(parsed.reason, "флуд")

    def test_parse_mute_with_compact_duration(self) -> None:
        parsed = self.parser.parse("мут @User 30м флуд", has_reply=False)
        self.assertEqual(parsed.explicit_target.username, "User")
        self.assertEqual(parsed.duration_seconds, 1800)
        self.assertEqual(parsed.reason, "флуд")

    def test_parse_mute_with_merged_duration(self) -> None:
        parsed = self.parser.parse("мут @User 30мин флуд", has_reply=False)
        self.assertEqual(parsed.explicit_target.username, "User")
        self.assertEqual(parsed.duration_seconds, 1800)
        self.assertEqual(parsed.reason, "флуд")

    def test_parse_mute_with_split_short_duration(self) -> None:
        parsed = self.parser.parse("мут @User 1 ч", has_reply=False)
        self.assertEqual(parsed.explicit_target.username, "User")
        self.assertEqual(parsed.duration_seconds, 3600)

    def test_parse_mute_with_dotted_abbreviation(self) -> None:
        parsed = self.parser.parse("мут @User 30 мин. флуд", has_reply=False)
        self.assertEqual(parsed.explicit_target.username, "User")
        self.assertEqual(parsed.duration_seconds, 1800)
        self.assertEqual(parsed.reason, "флуд")

    def test_parse_mute_with_duration_before_target(self) -> None:
        parsed = self.parser.parse("мут 1 час @User флуд", has_reply=False)
        self.assertEqual(parsed.explicit_target.username, "User")
        self.assertEqual(parsed.duration_seconds, 3600)
        self.assertEqual(parsed.reason, "флуд")

    def test_parse_mute_with_reason_target_duration(self) -> None:
        parsed = self.parser.parse("мут флуд @User 5 часов", has_reply=False)
        self.assertEqual(parsed.explicit_target.username, "User")
        self.assertEqual(parsed.duration_seconds, 5 * 3600)
        self.assertEqual(parsed.reason, "флуд")

    def test_parse_mute_with_target_reason_duration(self) -> None:
        parsed = self.parser.parse("м @User флуд 1 час", has_reply=False)
        self.assertEqual(parsed.explicit_target.username, "User")
        self.assertEqual(parsed.duration_seconds, 3600)
        self.assertEqual(parsed.reason, "флуд")

    def test_parse_mute_with_user_id_and_split_duration(self) -> None:
        parsed = self.parser.parse("мут 123456 5 дней спам", has_reply=False)
        self.assertEqual(parsed.explicit_target.user_id, 123456)
        self.assertEqual(parsed.duration_seconds, 5 * 86400)
        self.assertEqual(parsed.reason, "спам")

    def test_parse_mute_with_long_duration_above_old_cap(self) -> None:
        parsed = self.parser.parse("мут @User 90 дней флуд", has_reply=False)
        self.assertEqual(parsed.explicit_target.username, "User")
        self.assertEqual(parsed.duration_seconds, 90 * 86400)
        self.assertEqual(parsed.reason, "флуд")

    def test_parse_mute_with_combined_duration(self) -> None:
        parsed = self.parser.parse("мут @User 1 час 30 минут флуд", has_reply=False)
        self.assertEqual(parsed.explicit_target.username, "User")
        self.assertEqual(parsed.duration_seconds, 5400)
        self.assertEqual(parsed.reason, "флуд")

    def test_parse_reply_with_same_explicit_target_is_kept(self) -> None:
        parsed = self.parser.parse("мут @user 30 минут", has_reply=True)
        self.assertEqual(parsed.kind, CommandKind.MUTE)
        self.assertEqual(parsed.explicit_target.username, "user")
        self.assertEqual(parsed.duration_seconds, 1800)

    def test_parse_reply_with_same_explicit_user_id_is_kept(self) -> None:
        parsed = self.parser.parse("бан 123456 1 день", has_reply=True)
        self.assertEqual(parsed.kind, CommandKind.BAN)
        self.assertEqual(parsed.explicit_target.user_id, 123456)
        self.assertEqual(parsed.duration_seconds, 86400)

    def test_parse_kick_with_reason_after_target(self) -> None:
        parsed = self.parser.parse("кик @User причина", has_reply=False)
        self.assertEqual(parsed.kind, CommandKind.KICK)
        self.assertEqual(parsed.explicit_target.username, "User")
        self.assertEqual(parsed.reason, "причина")

    def test_parse_kick_with_reason_before_target(self) -> None:
        parsed = self.parser.parse("кик причина @User", has_reply=False)
        self.assertEqual(parsed.kind, CommandKind.KICK)
        self.assertEqual(parsed.explicit_target.username, "User")
        self.assertEqual(parsed.reason, "причина")

    def test_parse_reply_kick_with_reason(self) -> None:
        parsed = self.parser.parse("кик причина", has_reply=True)
        self.assertEqual(parsed.kind, CommandKind.KICK)
        self.assertIsNone(parsed.explicit_target)
        self.assertEqual(parsed.reason, "причина")

    def test_parse_reply_kick_without_reason(self) -> None:
        parsed = self.parser.parse("кик", has_reply=True)
        self.assertEqual(parsed.kind, CommandKind.KICK)
        self.assertIsNone(parsed.reason)

    def test_parse_timed_ban_with_target_first(self) -> None:
        parsed = self.parser.parse("бан @User 1м спам", has_reply=False)
        self.assertEqual(parsed.kind, CommandKind.BAN)
        self.assertEqual(parsed.explicit_target.username, "User")
        self.assertEqual(parsed.duration_seconds, 60)
        self.assertEqual(parsed.reason, "спам")

    def test_parse_timed_ban_with_duration_before_target(self) -> None:
        parsed = self.parser.parse("бан 2 дня @User спам", has_reply=False)
        self.assertEqual(parsed.explicit_target.username, "User")
        self.assertEqual(parsed.duration_seconds, 2 * 86400)
        self.assertEqual(parsed.reason, "спам")

    def test_parse_timed_ban_with_implicit_duration(self) -> None:
        parsed = self.parser.parse("бан @User неделя", has_reply=False)
        self.assertEqual(parsed.explicit_target.username, "User")
        self.assertEqual(parsed.duration_seconds, 7 * 86400)
        self.assertIsNone(parsed.reason)

    def test_parse_reply_timed_ban_with_implicit_day(self) -> None:
        parsed = self.parser.parse("бан день спам", has_reply=True)
        self.assertEqual(parsed.duration_seconds, 86400)
        self.assertEqual(parsed.reason, "спам")

    def test_parse_reply_timed_ban_with_implicit_hour(self) -> None:
        parsed = self.parser.parse("бан час флуд", has_reply=True)
        self.assertEqual(parsed.duration_seconds, 3600)
        self.assertEqual(parsed.reason, "флуд")

    def test_parse_timed_ban_with_merged_duration(self) -> None:
        parsed = self.parser.parse("бан @User 2дня спам", has_reply=False)
        self.assertEqual(parsed.explicit_target.username, "User")
        self.assertEqual(parsed.duration_seconds, 2 * 86400)
        self.assertEqual(parsed.reason, "спам")

    def test_parse_reply_permanent_ban(self) -> None:
        parsed = self.parser.parse("бан", has_reply=True)
        self.assertIsNone(parsed.duration_seconds)
        self.assertIsNone(parsed.reason)

    def test_parse_timed_ban_with_combined_duration(self) -> None:
        parsed = self.parser.parse("бан @User 1 день 2 часа", has_reply=False)
        self.assertEqual(parsed.explicit_target.username, "User")
        self.assertEqual(parsed.duration_seconds, 86400 + 7200)

    def test_parse_timed_ban_with_very_long_duration(self) -> None:
        parsed = self.parser.parse("бан @User 400 дней", has_reply=False)
        self.assertEqual(parsed.explicit_target.username, "User")
        self.assertEqual(parsed.duration_seconds, 400 * 86400)

    def test_parse_unban_by_user_id(self) -> None:
        parsed = self.parser.parse("разбан 123456789", has_reply=False)
        self.assertEqual(parsed.kind, CommandKind.UNBAN)
        self.assertEqual(parsed.explicit_target.user_id, 123456789)

    def test_parse_set_level_with_flexible_order(self) -> None:
        parsed = self.parser.parse("уровень 3 @user", has_reply=False)
        self.assertEqual(parsed.kind, CommandKind.SET_LEVEL)
        self.assertEqual(parsed.explicit_target.username, "user")
        self.assertEqual(parsed.level, 3)

    def test_parse_set_level_with_target_first(self) -> None:
        parsed = self.parser.parse("уровень @user 3", has_reply=False)
        self.assertEqual(parsed.kind, CommandKind.SET_LEVEL)
        self.assertEqual(parsed.explicit_target.username, "user")
        self.assertEqual(parsed.level, 3)

    def test_parse_raise_explicit_with_flexible_order(self) -> None:
        parsed = self.parser.parse("повысить 2 @user", has_reply=False)
        self.assertEqual(parsed.kind, CommandKind.RAISE_LEVEL)
        self.assertEqual(parsed.explicit_target.username, "user")
        self.assertEqual(parsed.level, 2)
        self.assertIsNone(parsed.level_delta)

    def test_parse_lower_explicit_with_flexible_order(self) -> None:
        parsed = self.parser.parse("понизить 1 @user", has_reply=False)
        self.assertEqual(parsed.kind, CommandKind.LOWER_LEVEL)
        self.assertEqual(parsed.explicit_target.username, "user")
        self.assertEqual(parsed.level, 1)

    def test_parse_raise_implicit(self) -> None:
        parsed = self.parser.parse("повысить @user", has_reply=False)
        self.assertEqual(parsed.kind, CommandKind.RAISE_LEVEL)
        self.assertEqual(parsed.level_delta, 1)
        self.assertIsNone(parsed.level)

    def test_parse_lower_implicit_by_reply(self) -> None:
        parsed = self.parser.parse("понизить", has_reply=True)
        self.assertEqual(parsed.kind, CommandKind.LOWER_LEVEL)
        self.assertEqual(parsed.level_delta, -1)

    def test_parse_view_level_by_reply_with_explicit_target(self) -> None:
        parsed = self.parser.parse("уровень @user", has_reply=True)
        self.assertEqual(parsed.kind, CommandKind.VIEW_LEVEL)
        self.assertEqual(parsed.explicit_target.username, "user")

    def test_parse_reject_multiple_targets(self) -> None:
        with self.assertRaises(ParseCommandError):
            self.parser.parse("мут @user @other 30м", has_reply=False)

    def test_parse_reject_multiple_durations(self) -> None:
        with self.assertRaises(ParseCommandError):
            self.parser.parse("мут @user 30м флуд 1 час", has_reply=False)

    def test_parse_reject_missing_target_for_ban(self) -> None:
        with self.assertRaises(ParseCommandError):
            self.parser.parse("бан причина", has_reply=False)

    def test_parse_reject_ambiguous_numeric_level_command(self) -> None:
        with self.assertRaises(ParseCommandError):
            self.parser.parse("уровень 3", has_reply=False)

    def test_parse_reject_extra_tokens_for_unmute(self) -> None:
        with self.assertRaises(ParseCommandError):
            self.parser.parse("анмут @user сейчас", has_reply=False)

    def test_parse_reject_level_five_assignment(self) -> None:
        with self.assertRaises(ValidationError):
            self.parser.parse("уровень @user 5", has_reply=False)


if __name__ == "__main__":
    unittest.main()
