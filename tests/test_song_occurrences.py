import unittest

from song_occurrences import (
    build_occurrences,
    evidence_role,
    evidence_kind,
    evidence_view_for_year,
    has_complete_setlist,
    noisy_or,
    occurrences_from_public_events,
    occurrences_from_youtube_setlists,
    parse_event_date,
    prediction_probability,
)


class SongOccurrencesTest(unittest.TestCase):
    def test_parses_japanese_event_date(self):
        self.assertEqual(
            parse_event_date("2026年5月24日行われました"),
            "2026-05-24",
        )

    def test_parses_english_event_date(self):
        self.assertEqual(
            parse_event_date("Saturday night, June 28th, 2025"),
            "2025-06-28",
        )

    def test_detects_announcement_and_complete_setlist(self):
        text = "曲目表\n1 東京音頭\n2 炭坑節\n3 山王音頭"
        self.assertEqual(evidence_kind(text), "announced")
        self.assertTrue(has_complete_setlist(text))

    def test_current_year_probabilities_follow_priority(self):
        rows = [
            {"year": 2026, "kind": "announced", "role": "prediction", "speaker": "b", "reliability": 0.8},
        ]
        result = prediction_probability(rows, 2026)
        self.assertEqual(result["basis"], "current_announced")
        self.assertEqual(result["probability"], 80)

    def test_combines_prediction_reliability_with_noisy_or(self):
        self.assertAlmostEqual(noisy_or([0.95, 0.8]), 0.99)

    def test_evidence_role_uses_time_boundary(self):
        self.assertEqual(
            evidence_role("2026-06-08T00:00:00+09:00", "2026-06-13T18:00:00+09:00", "announced"),
            "prediction",
        )
        self.assertEqual(
            evidence_role("2026-06-16T00:00:00+09:00", "2026-06-13T18:00:00+09:00", "observed"),
            "result",
        )

    def test_past_evidence_decays_and_uses_speaker_count(self):
        rows = [{"year": 2025, "kind": "observed", "speaker": "same-channel"}]
        result = prediction_probability(rows, 2026)
        self.assertEqual(result["basis"], "past_evidence")
        self.assertLess(result["probability"], 95)

    def test_builds_occurrences_from_review_and_public_events(self):
        data = build_occurrences(target_year=2026, generated_at="2026-06-13T00:00:00+00:00")
        self.assertGreaterEqual(data["occurrence_count"], 1)
        self.assertGreaterEqual(data["song_relation_count"], 1)

    def test_manual_sanno_evidence_is_included(self):
        data = build_occurrences(target_year=2026, generated_at="2026-06-13T00:00:00+00:00")
        sanno = [
            occurrence for occurrence in data["occurrences"]
            if occurrence["event_name"] == "山王音頭と民踊大会"
            and occurrence["year"] == 2026
        ]
        self.assertEqual(len(sanno), 1)
        self.assertGreaterEqual(len(sanno[0]["songs"]), 19)
        manual_songs = [
            song for song in sanno[0]["songs"]
            if any(ev["source"] == "manual_ocr" for ev in song["evidence"])
        ]
        self.assertEqual(len(manual_songs), 19)
        self.assertTrue(all(song["prediction"]["probability"] >= 80 for song in manual_songs))
        self.assertIn("predictions", sanno[0])
        self.assertIn("existence", sanno[0]["predictions"])
        self.assertIn("date", sanno[0]["predictions"])
        self.assertTrue(sanno[0]["observations"])
        self.assertTrue(
            all(any(ev["role"] == "prediction" and ev["dancer_key"] == "@ochiai_hrs" for ev in song["evidence"])
                for song in manual_songs)
        )
        self.assertTrue(
            any(any(ev["source"] == "youtube_setlist_occurrence" for ev in song["evidence"])
                for song in sanno[0]["songs"])
        )

    def test_youtube_setlists_emit_result_evidence(self):
        grouped = occurrences_from_youtube_setlists({
            "occurrences": [
                {
                    "canonical_event_name": "横浜開港祭 BON ODORI",
                    "canonical_venue": "パシフィコ横浜プラザ広場",
                    "event_date": "2026-06-01",
                    "accounts": ["@wadaikoCH"],
                    "song_count": 3,
                    "setlist": [
                        {"title": "東京音頭", "url": "https://www.youtube.com/watch?v=abc"},
                    ],
                    "source_videos": [
                        {
                            "url": "https://www.youtube.com/watch?v=abc",
                            "account": "@wadaikoCH",
                            "published_at": "2026-06-02T00:00:00+00:00",
                        }
                    ],
                }
            ]
        })
        key = ("横浜開港祭 BON ODORI", "パシフィコ横浜プラザ広場", 2026, "東京音頭")
        self.assertIn(key, grouped)
        evidence = grouped[key][0]
        self.assertEqual(evidence["role"], "result")
        self.assertEqual(evidence["source"], "youtube_setlist_occurrence")
        self.assertEqual(evidence["speaker"], "@wadaikoCH")
        self.assertEqual(evidence["reliability_key"], "complete_numbered_video")

    def test_youtube_setlists_canonicalize_marronnier_event(self):
        grouped = occurrences_from_youtube_setlists({
            "occurrences": [
                {
                    "event_name_hint": "マロニエまつり盆踊り大会 2 ヒューリック浅草橋ビル前(全曲ver)",
                    "venue": "ヒューリック浅草橋前",
                    "event_date": "2026-05-09",
                    "accounts": ["@matsuribonodori"],
                    "song_count": 3,
                    "setlist": [
                        {"title": "東京音頭", "url": "https://www.youtube.com/watch?v=abc"},
                    ],
                    "source_videos": [
                        {
                            "url": "https://www.youtube.com/watch?v=abc",
                            "account": "@matsuribonodori",
                            "published_at": "2026-05-13T00:00:00+00:00",
                        }
                    ],
                }
            ]
        })
        key = ("浅草橋マロニエまつり盆踊り", "ヒューリック浅草橋ビル前", 2026, "東京音頭")
        self.assertIn(key, grouped)
        self.assertEqual(grouped[key][0]["text"], (
            "マロニエまつり盆踊り大会 2 ヒューリック浅草橋ビル前(全曲ver) / "
            "ヒューリック浅草橋前 / 2026-05-09 / 東京音頭"
        ))

    def test_youtube_setlists_remove_occurrence_year_from_event_name(self):
        grouped = occurrences_from_youtube_setlists({
            "occurrences": [
                {
                    "event_name_hint": "郡上おどり in 青山 2025",
                    "venue": "秩父宮ラグビー場駐車場",
                    "event_date": "2025-06-20",
                    "accounts": ["@ch"],
                    "song_count": 3,
                    "setlist": [
                        {"title": "かわさき", "url": "https://www.youtube.com/watch?v=abc"},
                    ],
                }
            ]
        })

        key = ("郡上おどり in 青山", "秩父宮ラグビー場駐車場", 2025, "かわさき")
        self.assertIn(key, grouped)

    def test_public_event_song_hints_are_curated_predictions(self):
        grouped = occurrences_from_public_events([
            {
                "name": "築地本願寺納涼盆踊り大会",
                "venue": "築地本願寺",
                "date": "2026-07-29",
                "songs": [
                    {"name": "あやめ踊り", "confidence": "hint", "source_count": 1},
                ],
            }
        ])
        key = ("築地本願寺納涼盆踊り大会", "築地本願寺", 2026, "あやめ踊り")
        evidence = grouped[key][0]
        self.assertEqual(evidence["reliability_key"], "curated_public_song")
        result = prediction_probability(grouped[key], 2026)
        self.assertEqual(result["basis"], "current_hint")
        self.assertEqual(result["probability"], 80)

    def test_inherited_evidence_is_demoted_to_prediction(self):
        evidence = [
            {"year": 2025, "role": "result", "kind": "observed",
             "setlist_complete": True, "reliability": 0.95, "speaker": "@ch"},
            {"year": 2026, "role": "prediction", "kind": "announced",
             "reliability": 0.8, "speaker": "@x"},
            {"year": 2027, "role": "result", "kind": "observed", "speaker": "@future"},
        ]
        view = evidence_view_for_year(evidence, 2026)
        self.assertEqual(sorted(ev["year"] for ev in view), [2025, 2026])  # 未来年は除外
        inherited = [ev for ev in view if ev.get("inherited")]
        self.assertEqual(len(inherited), 1)
        self.assertEqual(inherited[0]["role"], "prediction")  # result を継承根拠に降格
        self.assertEqual(inherited[0]["source_year"], 2025)
        current = [ev for ev in view if not ev.get("inherited")]
        self.assertEqual(current[0]["year"], 2026)

    def test_inherited_past_evidence_is_overridden_by_current_info(self):
        past_only = evidence_view_for_year(
            [{"year": 2025, "role": "result", "kind": "observed",
              "setlist_complete": True, "reliability": 0.95, "speaker": "@ch"}],
            2026,
        )
        self.assertEqual(prediction_probability(past_only, 2026)["basis"], "past_evidence")
        with_current = past_only + [
            {"year": 2026, "role": "prediction", "kind": "announced",
             "reliability": 0.8, "speaker": "@x"},
        ]
        self.assertEqual(prediction_probability(with_current, 2026)["basis"], "current_announced")


if __name__ == "__main__":
    unittest.main()
