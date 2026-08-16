import json
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from unittest.mock import patch

from apply_x_extraction_results import apply, main as apply_main


FIXED_NOW = datetime(2026, 8, 16, 12, tzinfo=timezone.utc)


def item(no=1, tweet_id="t1", text="東京音頭を踊った", **extra):
    return {
        "no": no,
        "tweet_id": tweet_id,
        "url": f"https://x.example/{tweet_id}",
        "posted_at": "2026-08-16T00:00:00+00:00",
        "account": "@person",
        "officiality": "unknown_or_personal_social",
        "text": text,
        "machine_extracted_dates": [],
        **extra,
    }


def valid_event(**extra):
    return {
        "event_name": "試験盆踊り",
        "date_start": "2099-08-20",
        "venue_name": "試験公園",
        "quote": "8月20日に試験公園で試験盆踊りを開催",
        **extra,
    }


class XPostExtractionSongsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.reports_dir = Path(self.temp.name) / "reports"

    def tearDown(self):
        self.temp.cleanup()

    def run_apply(self, results, *, items=None, song_ledger=None, glossary_ledger=None, state=None):
        packet_items = items or [item()]
        packet = {"batch_id": "x", "packets": packet_items}
        answer = {"batch_id": "x", "results": results}
        state = state if state is not None else {"tweets": {}}
        song_ledger = song_ledger if song_ledger is not None else {"observations": []}
        glossary_ledger = glossary_ledger if glossary_ledger is not None else {"terms": []}
        result = apply(
            packet,
            answer,
            state,
            self.reports_dir,
            song_ledger=song_ledger,
            glossary_ledger=glossary_ledger,
            today=date(2026, 8, 16),
            now=FIXED_NOW,
        )
        return result, song_ledger, glossary_ledger, state

    # 1. 本文にある曲名は台帳へ入る。
    def test_acceptance_01_records_song_found_in_text(self):
        result, songs, _, _ = self.run_apply([
            {"no": 1, "s": 4, "observations": [{"event_name": None, "songs": ["東京音頭"]}]}
        ])
        self.assertEqual(result["song_observation_count"], 1)
        self.assertEqual(songs["observations"][0]["song_name"], "東京音頭")

    # 2. 本文にない曲名は捏造issueとして落ちる。
    def test_acceptance_02_rejects_song_not_found_in_text(self):
        result, songs, _, _ = self.run_apply([
            {"no": 1, "s": 4, "observations": [{"event_name": None, "songs": ["炭坑節"]}]}
        ])
        self.assertEqual(songs["observations"], [])
        self.assertIn("song_not_in_text", [row["issue_type"] for row in result["issues"]])

    # 3. 1曲の失敗で同じ観測の他曲を失わない。
    def test_acceptance_03_keeps_valid_song_when_sibling_is_invalid(self):
        result, songs, _, _ = self.run_apply([
            {"no": 1, "s": 4, "observations": [{"event_name": None, "songs": ["炭坑節", "東京音頭"]}]}
        ])
        self.assertEqual([row["song_name"] for row in songs["observations"]], ["東京音頭"])
        self.assertEqual(result["song_issue_count"], 1)

    # 4. event_name:null は行事不明の観測として保持する。
    def test_acceptance_04_records_null_event_name(self):
        _, songs, _, _ = self.run_apply([
            {"no": 1, "s": 4, "observations": [{"event_name": None, "songs": ["東京音頭"]}]}
        ])
        self.assertIsNone(songs["observations"][0]["event_name"])

    # 5. 同じ曲でも行事が違えば多対多の別観測になる。
    def test_acceptance_05_same_song_with_different_events_is_distinct(self):
        _, songs, _, _ = self.run_apply([
            {"no": 1, "s": 4, "observations": [
                {"event_name": "東町盆踊り", "songs": ["東京音頭"]},
                {"event_name": "西町盆踊り", "songs": ["東京音頭"]},
            ]}
        ], items=[item(text="東町盆踊りと西町盆踊りで東京音頭を踊った")])
        self.assertEqual(len(songs["observations"]), 2)
        self.assertEqual(len({row["observation_id"] for row in songs["observations"]}), 2)

    # 6. 同じ回答の再取り込みで曲観測が増えない。
    def test_acceptance_06_song_observations_are_idempotent(self):
        results = [{"no": 1, "s": 4, "observations": [{"event_name": None, "songs": ["東京音頭"]}]}]
        _, songs, glossary, state = self.run_apply(results)
        result, songs, _, _ = self.run_apply(
            results, song_ledger=songs, glossary_ledger=glossary, state=state
        )
        self.assertEqual(len(songs["observations"]), 1)
        self.assertEqual(result["song_observation_count"], 0)

    # 7. 5点の events[].songs も観測になる。
    def test_acceptance_07_records_songs_from_five_point_event(self):
        event = valid_event(songs=["東京音頭"])
        _, songs, _, _ = self.run_apply(
            [{"no": 1, "s": 5, "events": [event]}],
            items=[item(text="8月20日に試験公園で試験盆踊りを開催 東京音頭", machine_extracted_dates=["2099-08-20"])],
        )
        self.assertEqual(songs["observations"][0]["song_name"], "東京音頭")

    # 8. 4点の曲観測はE0レポートを作らない。
    def test_acceptance_08_four_point_observation_never_creates_e0_report(self):
        result, _, _, state = self.run_apply([
            {"no": 1, "s": 4, "observations": [{"event_name": None, "songs": ["東京音頭"]}]}
        ])
        self.assertEqual(result["report_count"], 0)
        self.assertEqual(list(self.reports_dir.glob("*.json")), [])
        self.assertEqual(state["tweets"]["t1"]["outcome"], "scored_only")

    # 9. 本文にある界隈語は台帳へ入る。
    def test_acceptance_09_records_glossary_term_found_in_text(self):
        _, _, glossary, _ = self.run_apply(
            [{"no": 1, "s": 4, "glossary": ["盆オドラー"]}],
            items=[item(text="盆オドラーが集まる夜")],
        )
        self.assertEqual(glossary["terms"][0]["term"], "盆オドラー")

    # 10. 本文にない界隈語はissueとして落ちる。
    def test_acceptance_10_rejects_glossary_term_not_found_in_text(self):
        result, _, glossary, _ = self.run_apply([
            {"no": 1, "s": 4, "glossary": ["盆オドラー"]}
        ])
        self.assertEqual(glossary["terms"], [])
        self.assertIn("term_not_in_text", [row["issue_type"] for row in result["issues"]])

    # 11. 同じ語は集約し、例は5件で止まる。
    def test_acceptance_11_aggregates_terms_and_caps_examples_at_five(self):
        items = [item(no=i, tweet_id=f"t{i}", text="櫓のまわりで踊る") for i in range(1, 7)]
        results = [{"no": i, "s": 4, "glossary": ["櫓"]} for i in range(1, 7)]
        _, _, glossary, _ = self.run_apply(results, items=items)
        row = glossary["terms"][0]
        self.assertEqual(row["count"], 6)
        self.assertEqual(len(row["examples"]), 5)

    # 12. 中黒・長音・全角半角の差を吸収する。
    def test_acceptance_12_normalizes_middle_dot_long_mark_and_width(self):
        _, songs, _, _ = self.run_apply(
            [{"no": 1, "s": 4, "observations": [{"event_name": None, "songs": ["ダンシングヒロABC"]}]}],
            items=[item(text="ダンシング・ヒーローＡＢＣを踊る")],
        )
        self.assertEqual(len(songs["observations"]), 1)

    # 13. ひらがな・カタカナは同一視しない。
    def test_acceptance_13_does_not_fold_hiragana_and_katakana(self):
        result, songs, _, _ = self.run_apply(
            [{"no": 1, "s": 4, "observations": [{"event_name": None, "songs": ["盆おどり"]}]}],
            items=[item(text="盆オドリの話")],
        )
        self.assertEqual(songs["observations"], [])
        self.assertIn("song_not_in_text", [row["issue_type"] for row in result["issues"]])

    # 14. observations全体が壊れても採点・5点レポートを続ける。
    def test_acceptance_14_malformed_observations_do_not_stop_other_processing(self):
        event = valid_event()
        result, _, glossary, _ = self.run_apply(
            [{"no": 1, "s": 5, "events": [event], "observations": {}, "glossary": ["櫓"]}],
            items=[item(text="8月20日に試験公園で試験盆踊りを開催 櫓", machine_extracted_dates=["2099-08-20"])],
        )
        self.assertEqual(result["score_count"], 1)
        self.assertEqual(result["report_count"], 1)
        self.assertEqual(glossary["terms"][0]["term"], "櫓")
        self.assertIn("malformed_observation", [row["issue_type"] for row in result["issues"]])

    # 15. 観測の有無でstate outcome語彙を増やさない。
    def test_acceptance_15_observations_do_not_change_outcome_vocabulary(self):
        _, _, _, state = self.run_apply([
            {"no": 1, "s": 4, "observations": [{"event_name": None, "songs": ["東京音頭"]}]}
        ])
        self.assertEqual(state["tweets"]["t1"]["outcome"], "scored_only")

    # 16. 取り込みレポートに今回件数と累計が出る。
    def test_acceptance_16_reports_batch_and_total_counts(self):
        result, _, _, _ = self.run_apply(
            [{"no": 1, "s": 4,
              "observations": [{"event_name": None, "songs": ["東京音頭"]}],
              "glossary": ["櫓"]}],
            items=[item(text="東京音頭を櫓のまわりで踊る")],
        )
        self.assertEqual(result["song_observation_count"], 1)
        self.assertEqual(result["glossary_term_count"], 1)
        self.assertEqual(result["song_observations_total"], 1)
        self.assertEqual(result["glossary_terms_total"], 1)

    # 17. 第1段は occurrence_songs へ接続しない。
    def test_acceptance_17_has_no_occurrence_songs_write_path(self):
        source = (Path(__file__).resolve().parents[1] / "apply_x_extraction_results.py").read_text(encoding="utf-8")
        self.assertNotIn("occurrence_songs", source)
        self.assertNotIn("event_occurrences", source)

    # 18. examples満杯後も同じtweetの再取り込みでcountを増やさない。
    def test_acceptance_18_glossary_count_is_idempotent_after_examples_fill(self):
        items = [item(no=i, tweet_id=f"t{i}", text="櫓のまわりで踊る") for i in range(1, 7)]
        results = [{"no": i, "s": 4, "glossary": ["櫓"]} for i in range(1, 7)]
        _, songs, glossary, state = self.run_apply(results, items=items)
        row = glossary["terms"][0]
        self.assertEqual((row["count"], len(row["examples"])), (6, 5))
        self.run_apply(
            [{"no": 6, "s": 4, "glossary": ["櫓"]}],
            items=[items[-1]], song_ledger=songs, glossary_ledger=glossary, state=state,
        )
        self.assertEqual((row["count"], len(row["examples"])), (6, 5))

    # 19. countはsource_tweet_idsから導出する。
    def test_acceptance_19_count_always_matches_source_tweet_ids(self):
        items = [item(no=i, tweet_id=f"t{i}", text="ゆる盆の話") for i in range(1, 4)]
        results = [{"no": i, "s": 4, "glossary": ["ゆる盆"]} for i in range(1, 4)]
        _, _, glossary, _ = self.run_apply(results, items=items)
        row = glossary["terms"][0]
        self.assertEqual(row["count"], len(row["source_tweet_ids"]))

    # 20. event_name型破損は曲だけ落とし、glossaryと採点は続ける。
    def test_acceptance_20_bad_event_name_does_not_stop_glossary_or_scoring(self):
        result, songs, glossary, _ = self.run_apply(
            [{"no": 1, "s": 4,
              "observations": [{"event_name": {"bad": True}, "songs": ["東京音頭"]}],
              "glossary": ["櫓"]}],
            items=[item(text="東京音頭を櫓のまわりで踊る")],
        )
        self.assertEqual(songs["observations"], [])
        self.assertEqual(glossary["terms"][0]["term"], "櫓")
        self.assertEqual(result["score_count"], 1)
        self.assertIn("malformed_observation", [row["issue_type"] for row in result["issues"]])

    # 21. glossary型破損は曲・採点・5点レポートを止めない。
    def test_acceptance_21_bad_glossary_does_not_stop_song_score_or_report(self):
        event = valid_event(songs=["東京音頭"])
        result, songs, _, _ = self.run_apply(
            [{"no": 1, "s": 5, "events": [event], "glossary": "櫓"}],
            items=[item(text="8月20日に試験公園で試験盆踊りを開催 東京音頭", machine_extracted_dates=["2099-08-20"])],
        )
        self.assertEqual((len(songs["observations"]), result["score_count"], result["report_count"]), (1, 1, 1))
        self.assertIn("malformed_glossary", [row["issue_type"] for row in result["issues"]])

    # 22. eventsとobservationsを両方処理し、同じ組は重複排除する。
    def test_acceptance_22_merges_event_and_observation_sources_without_duplicates(self):
        event = valid_event(songs=["東京音頭"])
        _, songs, _, _ = self.run_apply(
            [{"no": 1, "s": 5, "events": [event], "observations": [
                {"event_name": "試験盆踊り", "songs": ["東京音頭"]},
                {"event_name": None, "songs": ["炭坑節"]},
            ]}],
            items=[item(text="8月20日に試験公園で試験盆踊りを開催 東京音頭と炭坑節", machine_extracted_dates=["2099-08-20"])],
        )
        self.assertEqual(len(songs["observations"]), 2)
        self.assertEqual({row["song_name"] for row in songs["observations"]}, {"東京音頭", "炭坑節"})

    # 23. 第2段で証拠種別を決められるようoriginを残す。
    def test_acceptance_23_records_origin_for_both_paths(self):
        event = valid_event(songs=["東京音頭"])
        _, songs, _, _ = self.run_apply(
            [{"no": 1, "s": 5, "events": [event],
              "observations": [{"event_name": None, "songs": ["炭坑節"]}]}],
            items=[item(text="8月20日に試験公園で試験盆踊りを開催 東京音頭と炭坑節", machine_extracted_dates=["2099-08-20"])],
        )
        origins = {row["song_name"]: row["origin"] for row in songs["observations"]}
        self.assertEqual(origins, {"東京音頭": "events", "炭坑節": "observations"})

    # 24. URL空でも観測は正本factではないので保持する。
    def test_acceptance_24_keeps_observations_without_url(self):
        result, songs, glossary, _ = self.run_apply(
            [{"no": 1, "s": 4,
              "observations": [{"event_name": None, "songs": ["東京音頭"]}],
              "glossary": ["櫓"]}],
            items=[item(text="東京音頭を櫓のまわりで踊る", url="")],
        )
        self.assertEqual((len(songs["observations"]), len(glossary["terms"])), (1, 1))
        self.assertNotIn("missing_source_url", [row["issue_type"] for row in result["issues"]])

    # 25. 曲と界隈語のissue件数を分ける。
    def test_acceptance_25_separates_song_and_glossary_issue_counts(self):
        result, _, _, _ = self.run_apply([
            {"no": 1, "s": 4,
             "observations": [{"event_name": None, "songs": ["炭坑節", "河内音頭"]}],
             "glossary": ["盆オドラー"]}
        ])
        self.assertEqual(result["song_issue_count"], 2)
        self.assertEqual(result["glossary_issue_count"], 1)

    # 基準では events は5点だけ。4点以下の events[].songs は観測にしない。
    def test_events_songs_ignored_when_score_is_not_five(self):
        event = valid_event(songs=["東京音頭"])
        _, songs, _, _ = self.run_apply(
            [{"no": 1, "s": 4, "events": [event]}],
            items=[item(
                text="8月20日に試験公園で試験盆踊りを開催 東京音頭",
                machine_extracted_dates=["2099-08-20"],
            )],
        )
        self.assertEqual(songs["observations"], [])

    def test_type_contract_rejects_non_string_song_and_term_independently(self):
        result, songs, glossary, _ = self.run_apply(
            [{"no": 1, "s": 4,
              "observations": [{"event_name": None, "songs": [None, "東京音頭"]}],
              "glossary": [{"bad": True}, "櫓"]}],
            items=[item(text="東京音頭を櫓のまわりで踊る")],
        )
        self.assertEqual((len(songs["observations"]), len(glossary["terms"])), (1, 1))
        issue_types = [row["issue_type"] for row in result["issues"]]
        self.assertIn("empty_song_name", issue_types)
        self.assertIn("malformed_term", issue_types)

    def test_cli_persists_both_ledgers_and_apply_report(self):
        root = Path(self.temp.name)
        packet_path = root / "packet.json"
        result_path = root / "result.json"
        state_path = root / "state.json"
        scores_path = root / "scores.json"
        songs_path = root / "songs.json"
        glossary_path = root / "glossary.json"
        report_path = root / "apply-report.json"
        packet_path.write_text(json.dumps({"batch_id": "x", "packets": [
            item(text="東京音頭を櫓のまわりで踊る")
        ]}), encoding="utf-8")
        result_path.write_text(json.dumps({"batch_id": "x", "results": [{
            "no": 1,
            "s": 4,
            "observations": [{"event_name": None, "songs": ["東京音頭"]}],
            "glossary": ["櫓"],
        }]}), encoding="utf-8")
        argv = [
            "apply_x_extraction_results.py",
            "--packet", str(packet_path),
            "--results", str(result_path),
            "--state", str(state_path),
            "--reports-dir", str(self.reports_dir),
            "--scores", str(scores_path),
            "--song-observations", str(songs_path),
            "--glossary-observations", str(glossary_path),
            "--out", str(report_path),
        ]
        with patch("sys.argv", argv):
            apply_main()

        self.assertEqual(len(json.loads(songs_path.read_text())["observations"]), 1)
        self.assertEqual(len(json.loads(glossary_path.read_text())["terms"]), 1)
        report = json.loads(report_path.read_text())
        self.assertEqual((report["song_observation_count"], report["glossary_term_count"]), (1, 1))


if __name__ == "__main__":
    unittest.main()
