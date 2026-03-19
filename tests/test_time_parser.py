from __future__ import annotations

import unittest
from datetime import timedelta

from utils.formatters import humanize_duration
from utils.time_parser import match_duration_tokens, parse_duration_token, timedelta_to_seconds


class TimeParserTests(unittest.TestCase):
    def test_parse_compact_minutes(self) -> None:
        duration = parse_duration_token("30м")
        self.assertEqual(duration, timedelta(minutes=30))
        self.assertEqual(timedelta_to_seconds(duration), 1800)

    def test_parse_compact_hours(self) -> None:
        duration = parse_duration_token("1ч")
        self.assertEqual(duration, timedelta(hours=1))

    def test_parse_compact_days(self) -> None:
        duration = parse_duration_token("2д")
        self.assertEqual(duration, timedelta(days=2))

    def test_parse_compact_weeks(self) -> None:
        duration = parse_duration_token("1н")
        self.assertEqual(duration, timedelta(weeks=1))

    def test_parse_merged_minutes(self) -> None:
        duration = parse_duration_token("30мин")
        self.assertEqual(duration, timedelta(minutes=30))

    def test_parse_merged_hours(self) -> None:
        duration = parse_duration_token("5часов")
        self.assertEqual(duration, timedelta(hours=5))

    def test_parse_merged_days(self) -> None:
        duration = parse_duration_token("2дня")
        self.assertEqual(duration, timedelta(days=2))

    def test_parse_merged_weeks(self) -> None:
        duration = parse_duration_token("1неделя")
        self.assertEqual(duration, timedelta(weeks=1))

    def test_parse_split_short_minutes(self) -> None:
        duration, consumed = match_duration_tokens(["30", "м"], 0)
        self.assertEqual(duration, timedelta(minutes=30))
        self.assertEqual(consumed, 2)

    def test_parse_split_short_hours(self) -> None:
        duration, consumed = match_duration_tokens(["1", "ч"], 0)
        self.assertEqual(duration, timedelta(hours=1))
        self.assertEqual(consumed, 2)

    def test_parse_split_short_days(self) -> None:
        duration, consumed = match_duration_tokens(["2", "д"], 0)
        self.assertEqual(duration, timedelta(days=2))
        self.assertEqual(consumed, 2)

    def test_parse_split_short_weeks(self) -> None:
        duration, consumed = match_duration_tokens(["1", "н"], 0)
        self.assertEqual(duration, timedelta(weeks=1))
        self.assertEqual(consumed, 2)

    def test_parse_split_dotted_abbreviation(self) -> None:
        duration, consumed = match_duration_tokens(["30", "мин."], 0)
        self.assertEqual(duration, timedelta(minutes=30))
        self.assertEqual(consumed, 2)

    def test_parse_full_word_minutes(self) -> None:
        duration, consumed = match_duration_tokens(["30", "минут"], 0)
        self.assertEqual(duration, timedelta(minutes=30))
        self.assertEqual(consumed, 2)

    def test_parse_full_word_hours(self) -> None:
        duration, consumed = match_duration_tokens(["5", "часов"], 0)
        self.assertEqual(duration, timedelta(hours=5))
        self.assertEqual(consumed, 2)

    def test_parse_full_word_days(self) -> None:
        duration, consumed = match_duration_tokens(["5", "дней"], 0)
        self.assertEqual(duration, timedelta(days=5))
        self.assertEqual(consumed, 2)

    def test_parse_full_word_weeks(self) -> None:
        duration, consumed = match_duration_tokens(["2", "недели"], 0)
        self.assertEqual(duration, timedelta(weeks=2))
        self.assertEqual(consumed, 2)

    def test_parse_implicit_minute_word(self) -> None:
        duration, consumed = match_duration_tokens(["минута"], 0)
        self.assertEqual(duration, timedelta(minutes=1))
        self.assertEqual(consumed, 1)

    def test_parse_implicit_minute_accusative(self) -> None:
        duration, consumed = match_duration_tokens(["минуту"], 0)
        self.assertEqual(duration, timedelta(minutes=1))
        self.assertEqual(consumed, 1)

    def test_parse_implicit_minute_short(self) -> None:
        duration, consumed = match_duration_tokens(["мин"], 0)
        self.assertEqual(duration, timedelta(minutes=1))
        self.assertEqual(consumed, 1)

    def test_parse_implicit_hour(self) -> None:
        duration, consumed = match_duration_tokens(["час"], 0)
        self.assertEqual(duration, timedelta(hours=1))
        self.assertEqual(consumed, 1)

    def test_parse_implicit_day(self) -> None:
        duration, consumed = match_duration_tokens(["день"], 0)
        self.assertEqual(duration, timedelta(days=1))
        self.assertEqual(consumed, 1)

    def test_parse_implicit_week(self) -> None:
        duration, consumed = match_duration_tokens(["неделя"], 0)
        self.assertEqual(duration, timedelta(weeks=1))
        self.assertEqual(consumed, 1)

    def test_parse_implicit_dotted_abbreviation(self) -> None:
        duration, consumed = match_duration_tokens(["ч."], 0)
        self.assertEqual(duration, timedelta(hours=1))
        self.assertEqual(consumed, 1)

    def test_parse_combined_duration(self) -> None:
        duration, consumed = match_duration_tokens(["1", "час", "30", "минут"], 0)
        self.assertEqual(duration, timedelta(hours=1, minutes=30))
        self.assertEqual(consumed, 4)

    def test_parse_combined_compact_duration(self) -> None:
        duration, consumed = match_duration_tokens(["1ч", "30м"], 0)
        self.assertEqual(duration, timedelta(hours=1, minutes=30))
        self.assertEqual(consumed, 2)

    def test_humanize_hour(self) -> None:
        self.assertEqual(humanize_duration(3600), "1 час")

    def test_humanize_days(self) -> None:
        self.assertEqual(humanize_duration(3 * 86400), "3 дня")

    def test_invalid_duration(self) -> None:
        with self.assertRaises(Exception):
            parse_duration_token("31д")


if __name__ == "__main__":
    unittest.main()
