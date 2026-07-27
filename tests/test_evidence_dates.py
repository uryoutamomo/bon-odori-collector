import unittest

from youtube_backfill.evidence_dates import borrowed_public_date, public_date_is_evidence_for_video


class PublicDateIsEvidenceForVideoTest(unittest.TestCase):
    def test_past_public_date_may_be_borrowed(self):
        self.assertTrue(public_date_is_evidence_for_video("2025-08-02", "2025-08-05T10:00:00Z"))

    def test_same_day_publication_may_be_borrowed(self):
        self.assertTrue(public_date_is_evidence_for_video("2025-08-05", "2025-08-05T10:00:00Z"))

    def test_public_date_after_publication_is_rejected(self):
        # A 2025 video cannot depict the 2026 edition of the same series.
        self.assertFalse(public_date_is_evidence_for_video("2026-08-01", "2025-08-06T09:00:00Z"))

    def test_missing_public_date_is_rejected(self):
        self.assertFalse(public_date_is_evidence_for_video("", "2025-08-05T10:00:00Z"))
        self.assertFalse(public_date_is_evidence_for_video(None, "2025-08-05T10:00:00Z"))

    def test_missing_publication_date_leaves_the_match_as_the_only_evidence(self):
        self.assertTrue(public_date_is_evidence_for_video("2026-08-01", ""))
        self.assertTrue(public_date_is_evidence_for_video("2026-08-01", None))


class BorrowedPublicDateTest(unittest.TestCase):
    def test_returns_the_day_part_when_borrowable(self):
        self.assertEqual(borrowed_public_date("2025-08-02", "2025-08-05T10:00:00Z"), "2025-08-02")

    def test_returns_empty_when_not_borrowable(self):
        self.assertEqual(borrowed_public_date("2026-08-01", "2025-08-06T09:00:00Z"), "")


if __name__ == "__main__":
    unittest.main()
