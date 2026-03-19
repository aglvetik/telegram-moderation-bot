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

    def test_parse_mute_with_flexible_order_target_duration_reason(self) -> None:
        parsed = self.parser.parse("мут 30м @User флуд", has_reply=False)
        self.assertEqual(parsed.kind, CommandKind.MUTE)
        self.assertEqual(parsed.explicit_target.username, "User")
        self.assertEqual(parsed.duration_seconds, 1800)
        self.assertEqual(parsed.reason, "флуд")

    def test_parse_mute_with_target_duration_reason(self) -> None:
        parsed = self.parser.parse("мут @User 30м флуд", has_reply=False)
        self.assertEqual(parsed.kind, CommandKind.MUTE)
        self.assertEqual(parsed.explicit_target.username, "User")
        self.assertEqual(parsed.duration_seconds, 1800)
        self.assertEqual(parsed.reason, "флуд")

    def test_parse_mute_with_reason_before_target_and_duration(self) -> None:
        parsed = self.parser.parse("мут флуд @User 30м", has_reply=False)
        self.assertEqual(parsed.kind, CommandKind.MUTE)
        self.assertEqual(parsed.explicit_target.username, "User")
        self.assertEqual(parsed.duration_seconds, 1800)
        self.assertEqual(parsed.reason, "флуд")

    def test_parse_mute_with_target_reason_duration(self) -> None:
        parsed = self.parser.parse("мут @User флуд 30м", has_reply=False)
        self.assertEqual(parsed.kind, CommandKind.MUTE)
        self.assertEqual(parsed.explicit_target.username, "User")
        self.assertEqual(parsed.duration_seconds, 1800)
        self.assertEqual(parsed.reason, "флуд")

    def test_parse_mute_with_user_id_in_flexible_order(self) -> None:
        parsed = self.parser.parse("мут флуд 30м 123456", has_reply=False)
        self.assertEqual(parsed.kind, CommandKind.MUTE)
        self.assertEqual(parsed.explicit_target.user_id, 123456)
        self.assertEqual(parsed.duration_seconds, 1800)
        self.assertEqual(parsed.reason, "флуд")

    def test_parse_ban_with_reason_after_target(self) -> None:
        parsed = self.parser.parse("бан @User токсичность", has_reply=False)
        self.assertEqual(parsed.kind, CommandKind.BAN)
        self.assertEqual(parsed.explicit_target.username, "User")
        self.assertEqual(parsed.reason, "токсичность")

    def test_parse_ban_with_reason_before_target(self) -> None:
        parsed = self.parser.parse("бан токсичность @User", has_reply=False)
        self.assertEqual(parsed.kind, CommandKind.BAN)
        self.assertEqual(parsed.explicit_target.username, "User")
        self.assertEqual(parsed.reason, "токсичность")

    def test_parse_kick_with_reason_before_target(self) -> None:
        parsed = self.parser.parse("кик нарушение @User", has_reply=False)
        self.assertEqual(parsed.kind, CommandKind.KICK)
        self.assertEqual(parsed.explicit_target.username, "User")
        self.assertEqual(parsed.reason, "нарушение")

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

    def test_parse_raise_explicit_with_user_id_target(self) -> None:
        parsed = self.parser.parse("повысить 2 123456", has_reply=False)
        self.assertEqual(parsed.kind, CommandKind.RAISE_LEVEL)
        self.assertEqual(parsed.explicit_target.user_id, 123456)
        self.assertEqual(parsed.level, 2)

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

    def test_parse_view_level_by_reply(self) -> None:
        parsed = self.parser.parse("уровень", has_reply=True)
        self.assertEqual(parsed.kind, CommandKind.VIEW_LEVEL)

    def test_parse_set_level_by_reply(self) -> None:
        parsed = self.parser.parse("уровень 3", has_reply=True)
        self.assertEqual(parsed.kind, CommandKind.SET_LEVEL)
        self.assertEqual(parsed.level, 3)

    def test_parse_reject_multiple_targets(self) -> None:
        with self.assertRaises(ParseCommandError):
            self.parser.parse("мут @user @other 30м", has_reply=False)

    def test_parse_reject_multiple_durations(self) -> None:
        with self.assertRaises(ParseCommandError):
            self.parser.parse("мут @user 30м 1ч флуд", has_reply=False)

    def test_parse_reject_missing_target_for_ban(self) -> None:
        with self.assertRaises(ParseCommandError):
            self.parser.parse("бан причина", has_reply=False)

    def test_parse_reject_ambiguous_numeric_level_command(self) -> None:
        with self.assertRaises(ParseCommandError):
            self.parser.parse("уровень 3", has_reply=False)

    def test_parse_reject_reply_with_explicit_target(self) -> None:
        with self.assertRaises(ParseCommandError):
            self.parser.parse("повысить @user", has_reply=True)

    def test_parse_reject_extra_tokens_for_unmute(self) -> None:
        with self.assertRaises(ParseCommandError):
            self.parser.parse("анмут @user сейчас", has_reply=False)

    def test_parse_reject_level_five_assignment(self) -> None:
        with self.assertRaises(ValidationError):
            self.parser.parse("уровень @user 5", has_reply=False)


if __name__ == "__main__":
    unittest.main()
