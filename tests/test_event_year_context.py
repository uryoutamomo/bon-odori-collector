import unittest
from datetime import date

from event_model.year_context import (
    EventYearContext,
    EventYearContextError,
    normalize_target_year,
)


class EventYearContextTest(unittest.TestCase):
    def test_keeps_target_year_and_as_of_explicit(self):
        context = EventYearContext(target_year="2027", as_of="2026-12-15")
        self.assertEqual(context.target_year, 2027)
        self.assertEqual(context.previous_year, 2026)
        self.assertEqual(context.as_of, date(2026, 12, 15))

    def test_rejects_invalid_target_year_without_clock_fallback(self):
        for value in (None, True, 0, "current"):
            with self.subTest(value=value):
                with self.assertRaises(EventYearContextError):
                    normalize_target_year(value)

    def test_rejects_invalid_as_of(self):
        with self.assertRaises(EventYearContextError):
            EventYearContext(target_year=2027, as_of="today")


if __name__ == "__main__":
    unittest.main()
