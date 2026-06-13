import unittest

from song_occurrences import (
    build_occurrences,
    evidence_kind,
    has_complete_setlist,
    parse_event_date,
    prediction_probability,
)


class SongOccurrencesTest(unittest.TestCase):
    def test_parses_japanese_event_date(self):
        self.assertEqual(
            parse_event_date("2026年5月24日行われました"),
            "2026-05-24",
        )

    def test_detects_announcement_and_complete_setlist(self):
        text = "曲目表\n1 東京音頭\n2 炭坑節\n3 山王音頭"
        self.assertEqual(evidence_kind(text), "announced")
        self.assertTrue(has_complete_setlist(text))

    def test_current_year_probabilities_follow_priority(self):
        rows = [
            {"year": 2026, "kind": "observed", "speaker": "a"},
            {"year": 2026, "kind": "announced", "speaker": "b"},
        ]
        self.assertEqual(prediction_probability(rows, 2026)["probability"], 98)

    def test_past_evidence_decays_and_uses_speaker_count(self):
        rows = [{"year": 2025, "kind": "observed", "speaker": "same-channel"}]
        result = prediction_probability(rows, 2026)
        self.assertEqual(result["basis"], "past_evidence")
        self.assertLess(result["probability"], 95)

    def test_builds_occurrences_from_review_and_public_events(self):
        data = build_occurrences(target_year=2026, generated_at="2026-06-13T00:00:00+00:00")
        self.assertGreaterEqual(data["occurrence_count"], 1)
        self.assertGreaterEqual(data["song_relation_count"], 1)


if __name__ == "__main__":
    unittest.main()
