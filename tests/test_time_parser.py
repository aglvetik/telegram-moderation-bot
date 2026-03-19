from __future__ import annotations

import unittest
from datetime import timedelta

from utils.formatters import humanize_duration
from utils.time_parser import parse_duration_token, timedelta_to_seconds


class TimeParserTests(unittest.TestCase):
    def test_parse_minutes(self) -> None:
        duration = parse_duration_token("15м")
        self.assertEqual(duration, timedelta(minutes=15))
        self.assertEqual(timedelta_to_seconds(duration), 900)

    def test_parse_weeks(self) -> None:
        duration = parse_duration_token("2н")
        self.assertEqual(duration, timedelta(weeks=2))

    def test_humanize_hour(self) -> None:
        self.assertEqual(humanize_duration(3600), "1 час")

    def test_humanize_days(self) -> None:
        self.assertEqual(humanize_duration(3 * 86400), "3 дня")

    def test_invalid_duration(self) -> None:
        with self.assertRaises(Exception):
            parse_duration_token("31д")


if __name__ == "__main__":
    unittest.main()
