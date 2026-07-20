import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from review_console import data
from review_inbox_decision_stage import build_decision_stage, write_decision_stage


def console_row(decision="accept", apply_value="confirm_current_date", **raw_overrides):
    raw = {
        "inbox_id": "inbox_future",
        "kind": "current_year_confirmation",
        "title": "丸の内de盆踊り",
        "source_id": "official_source",
        "source_key": "marunouchi|2026",
    }
    raw.update(raw_overrides)
    return {
        "source_id": "review_inbox",
        "decision": decision,
        "apply_value": apply_value,
        "reviewer": "内田さん",
        "reviewed_at": "2026-07-17T14:00:00+00:00",
        "note": "確認済み",
        "raw": raw,
    }


def rare_signal_row(decision="accept", apply_value="stage_registration_candidate", note=""):
    return {
        "source_id": "review_inbox",
        "decision": decision,
        "apply_value": apply_value,
        "reviewer": "内田さん",
        "reviewed_at": "2026-07-19T02:00:00+00:00",
        "note": note,
        "raw": {
            "inbox_id": "inbox_rare",
            "kind": "rare_signal",
            "title": "佐竹ゲバゲバ盆踊り",
            "event_name": "佐竹ゲバゲバ盆踊り",
            "venue": "佐竹商店街",
            "event_year": 2026,
            "source_id": "rare_signal",
            "source_key": "new_event_candidate|event|x-status:1",
            "source_url": "https://x.com/example/status/1",
            "payload": {
                "candidate_id": "xoto_satake",
                "promotion_target": "event",
                "possible_event_name": "佐竹ゲバゲバ盆踊り",
                "possible_venue": "佐竹商店街",
            },
        },
    }


def youtube_evidence_row(decision="accept", apply_value="add_song_evidence"):
    return {
        "source_id": "review_inbox",
        "decision": decision,
        "apply_value": apply_value,
        "reviewer": "内田さん",
        "reviewed_at": "2026-07-20T02:00:00+00:00",
        "note": "動画と曲を確認",
        "raw": {
            "inbox_id": "inbox_youtube",
            "kind": "youtube_evidence",
            "title": "みたままつり 東京音頭",
            "event_name": "みたままつり",
            "event_year": 2025,
            "source_id": "youtube_evidence",
            "source_key": "video:abc123|year:2025",
            "source_url": "https://www.youtube.com/watch?v=abc123",
            "payload": {
                "video_id": "abc123",
                "action": "review_video_evidence",
                "title_song_candidates": ["東京音頭"],
            },
        },
    }


def b4_row(kind, source_id, apply_value, payload, decision="accept"):
    return {
        "source_id":"review_inbox", "decision":decision, "apply_value":apply_value,
        "reviewer":"内田さん", "reviewed_at":"2026-07-20T04:00:00+00:00", "note":"確認",
        "raw":{"inbox_id":f"inbox_{kind}","kind":kind,"title":kind,"source_id":source_id,"source_key":f"key:{kind}","payload":payload},
    }


class ReviewInboxDecisionStageTest(unittest.TestCase):
    def test_b4_inbox_ui_exposes_kind_specific_finite_actions(self):
        source = next(source for source in data.SOURCES if source.id == "review_inbox")
        expected = {
            "song":"stage_song_candidate", "term":"stage_term_candidate",
            "song_research":"stage_song_venue_evidence", "venue_candidate":"stage_venue_candidate",
        }
        for kind, first in expected.items():
            options = data.apply_options(source, {"kind":kind})
            self.assertEqual([option["value"] for option in options], [first,"needs_research","reject","hold"])

    def test_b4_accepts_stage_only_finite_domain_packets(self):
        rows = [
            b4_row("song","daily_song_candidate","stage_song_candidate",{"canonical_song_name":"盆ジョビ"}),
            b4_row("term","daily_term_candidate","stage_term_candidate",{"term":"やぐら"}),
            b4_row("song_research","daily_term_candidate","stage_song_venue_evidence",{"song_name":"東京音頭","venue":"靖国神社"}),
            b4_row("venue_candidate","accepted_venue_song_missing_venue","stage_venue_candidate",{"suggested_venue":"日枝神社"}),
        ]
        for index, row in enumerate(rows): row["raw"]["inbox_id"] += str(index)
        stage = build_decision_stage({"rows":rows})
        self.assertEqual(stage["route_counts"]["domain_stage"], 4)
        self.assertEqual(
            [row["domain_stage_type"] for row in stage["by_route"]["domain_stage"]],
            ["song_candidate","term_candidate","song_venue_evidence","venue_candidate"],
        )
        self.assertTrue(all(row["domain_candidate"]["write_mode"] == "staged_only" for row in stage["by_route"]["domain_stage"]))

    def test_b4_accept_fails_closed_on_wrong_action_source_or_identity(self):
        unsafe = b4_row("song","daily_song_candidate","confirm_current_date",{"canonical_song_name":"曲"})
        with self.assertRaisesRegex(ValueError,"must use stage_song_candidate"):
            build_decision_stage({"rows":[unsafe]})
        wrong_source = b4_row("term","other","stage_term_candidate",{"term":"用語"})
        with self.assertRaisesRegex(ValueError,"invalid action or source"):
            build_decision_stage({"rows":[wrong_source]})
        incomplete = b4_row("song_research","daily_term_candidate","stage_song_venue_evidence",{"song_name":"曲"})
        with self.assertRaisesRegex(ValueError,"missing required identity"):
            build_decision_stage({"rows":[incomplete]})
        no_key = b4_row("term","daily_term_candidate","stage_term_candidate",{"term":"用語"})
        no_key["raw"]["source_key"] = ""
        with self.assertRaisesRegex(ValueError,"requires source_key"):
            build_decision_stage({"rows":[no_key]})

    def test_b4_quality_and_gap_never_emit_domain_packets(self):
        source = next(source for source in data.SOURCES if source.id == "review_inbox")
        self.assertEqual([o["value"] for o in data.apply_options(source,{"kind":"publication_gap"})],["needs_research","reject","hold"])
        quality_options = data.apply_options(source,{"kind":"historical_quality","payload":{"issue_codes":["historical_songs_missing"]}})
        self.assertTrue(next(o for o in quality_options if o["value"] == "needs_date_research")["disabled"])
        self.assertFalse(next(o for o in quality_options if o["value"] == "needs_song_research")["disabled"])
        keep = b4_row("historical_quality","historical_reference_quality","keep_historical_reference",{},decision="accept")
        stage = build_decision_stage({"rows":[keep]})
        self.assertEqual(stage["route_counts"]["no_apply"],1)
        self.assertNotIn("domain_candidate",stage["by_route"]["no_apply"][0])

    def test_youtube_inbox_ui_exposes_only_finite_b3_actions(self):
        source = next(source for source in data.SOURCES if source.id == "review_inbox")
        options = data.apply_options(source, {"kind": "youtube_evidence"})

        self.assertEqual(
            [option["value"] for option in options],
            ["add_song_evidence", "needs_research", "reject", "hold"],
        )
        self.assertEqual(
            [option["decision"] for option in options],
            ["accept", "needs_research", "reject", "hold"],
        )
        self.assertIn("直接反映しません", data.route_note(source, {"kind": "youtube_evidence"}))
        self.assertEqual(
            data.action_group_for(source, {"kind": "youtube_evidence"})["id"],
            "youtube",
        )

    def test_youtube_accept_stages_finite_song_evidence_packet(self):
        stage = build_decision_stage({"rows": [youtube_evidence_row()]})

        self.assertEqual(stage["route_counts"]["domain_stage"], 1)
        row = stage["by_route"]["domain_stage"][0]
        self.assertEqual(row["domain_stage_type"], "youtube_song_evidence")
        self.assertEqual(row["youtube_evidence"]["video_id"], "abc123")
        self.assertEqual(row["youtube_evidence"]["title_song_candidates"], ["東京音頭"])
        self.assertEqual(row["youtube_evidence"]["write_mode"], "staged_only")

    def test_youtube_accept_rejects_unsafe_action_and_incomplete_evidence(self):
        with self.assertRaisesRegex(ValueError, "must stage add_song_evidence"):
            build_decision_stage(
                {"rows": [youtube_evidence_row(apply_value="confirm_current_date")]}
            )

        incomplete = youtube_evidence_row()
        incomplete["raw"]["payload"].pop("video_id")
        with self.assertRaisesRegex(ValueError, "requires video_id"):
            build_decision_stage({"rows": [incomplete]})

        non_youtube = youtube_evidence_row()
        non_youtube["raw"]["source_url"] = "https://example.com/watch?v=abc123"
        with self.assertRaisesRegex(ValueError, "requires video_id"):
            build_decision_stage({"rows": [non_youtube]})

    def test_rare_signal_inbox_ui_exposes_only_finite_b2_actions(self):
        source = next(source for source in data.SOURCES if source.id == "review_inbox")
        options = data.apply_options(source, {"kind": "rare_signal"})

        self.assertEqual(
            [option["value"] for option in options],
            ["stage_registration_candidate", "needs_research", "reject", "hold"],
        )
        self.assertEqual(
            [option["decision"] for option in options],
            ["accept", "needs_research", "reject", "hold"],
        )
        self.assertIn("非X確認URL", data.route_note(source, {"kind": "rare_signal"}))

    def test_rare_signal_accept_stages_finite_registration_candidate(self):
        stage = build_decision_stage(
            {"rows": [rare_signal_row(note="確認 https://example.jp/satake-bonodori")]}
        )

        self.assertEqual(stage["route_counts"]["domain_stage"], 1)
        row = stage["by_route"]["domain_stage"][0]
        self.assertEqual(row["domain_stage_type"], "rare_signal_registration_candidate")
        self.assertEqual(
            row["registration_candidate"]["confirmed_source_urls"],
            ["https://example.jp/satake-bonodori"],
        )
        self.assertEqual(row["registration_candidate"]["write_mode"], "staged_only")

    def test_rare_signal_x_only_accept_fails_closed_without_packet(self):
        with self.assertRaisesRegex(ValueError, "requires a non-X confirmation URL"):
            build_decision_stage(
                {"rows": [rare_signal_row(note="確認 https://x.com/example/status/1")]}
            )

    def test_rare_signal_accept_rejects_unsafe_action(self):
        with self.assertRaisesRegex(ValueError, "must stage a registration candidate"):
            build_decision_stage(
                {
                    "rows": [
                        rare_signal_row(
                            apply_value="confirm_current_date",
                            note="https://example.jp/event",
                        )
                    ]
                }
            )

    def test_rare_signal_accept_rejects_invalid_source_and_target(self):
        wrong_source = rare_signal_row(note="https://example.jp/event")
        wrong_source["raw"]["source_id"] = "official_source"
        with self.assertRaisesRegex(ValueError, "requires rare_signal source_id"):
            build_decision_stage({"rows": [wrong_source]})

        wrong_target = rare_signal_row(note="https://example.jp/event")
        wrong_target["raw"]["payload"]["promotion_target"] = "public_apply"
        with self.assertRaisesRegex(ValueError, "unsupported promotion target"):
            build_decision_stage({"rows": [wrong_target]})

    def test_rare_signal_accept_ignores_malformed_and_x_subdomain_urls(self):
        row = rare_signal_row()
        row["raw"]["payload"]["confirmed_source_urls"] = [
            "not-a-url",
            "https://mobile.twitter.com/example/status/1",
            "https://x.com:443/example/status/1",
        ]
        with self.assertRaisesRegex(ValueError, "requires a non-X confirmation URL"):
            build_decision_stage({"rows": [row]})

    def test_rare_signal_non_accept_routes_never_emit_apply_packet(self):
        research = rare_signal_row(decision="needs_research", apply_value="needs_research")
        hold = rare_signal_row(decision="hold", apply_value="hold")
        hold["raw"]["inbox_id"] = "inbox_rare_hold"
        reject = rare_signal_row(decision="reject", apply_value="reject")
        reject["raw"]["inbox_id"] = "inbox_rare_reject"
        stage = build_decision_stage({"rows": [research, hold, reject]})

        self.assertEqual(stage["route_counts"]["research_followup"], 1)
        self.assertEqual(stage["route_counts"]["no_apply"], 2)
        for route in ("research_followup", "no_apply"):
            for row in stage["by_route"][route]:
                self.assertNotIn("registration_candidate", row)

    def test_builds_change_request_and_inbox_update_packets(self):
        stage = build_decision_stage({"rows": [console_row()]})

        self.assertEqual(stage["decision_count"], 1)
        self.assertEqual(stage["route_counts"]["change_request"], 1)
        row = stage["by_route"]["change_request"][0]
        self.assertEqual(row["change_type"], "confirm_current_year_date")
        self.assertEqual(row["inbox_update"]["decision"], "accepted")
        self.assertEqual(row["inbox_update"]["decision_route"], "change_request")

    def test_routes_research_hold_and_domain_stage_without_apply(self):
        stage = build_decision_stage(
            {
                "rows": [
                    console_row(decision="needs_research", apply_value="needs_research"),
                    console_row(decision="hold", apply_value="hold", inbox_id="inbox_hold"),
                    console_row(
                        apply_value="stage_song_candidate",
                        inbox_id="inbox_song",
                        kind="song",
                        source_id="daily_song_candidate",
                        payload={"canonical_song_name": "盆ジョビ"},
                    ),
                ]
            }
        )

        self.assertEqual(stage["route_counts"]["research_followup"], 1)
        self.assertEqual(stage["route_counts"]["no_apply"], 1)
        self.assertEqual(stage["route_counts"]["domain_stage"], 1)
        self.assertNotIn("change_type", stage["by_route"]["domain_stage"][0])

    def test_unknown_accepted_route_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "no safe route"):
            build_decision_stage({"rows": [console_row(apply_value="free_form_action")]})

    def test_missing_reviewer_fails_before_staging(self):
        row = console_row()
        row["reviewer"] = ""

        with self.assertRaisesRegex(ValueError, "requires reviewer"):
            build_decision_stage({"rows": [row]})

    def test_write_creates_updates_and_route_files_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stage = build_decision_stage({"rows": [console_row()]})
            files = write_decision_stage(stage, root)

            updates = json.loads((root / "review_inbox_decision_updates.json").read_text())
            route = json.loads((root / "review_inbox_change_request_decisions.json").read_text())

        self.assertEqual(len(files), 1)
        self.assertEqual(updates["inbox_decision_updates"][0]["inbox_id"], "inbox_future")
        self.assertEqual(route["decision_route"], "change_request")
        self.assertEqual(route["write_mode"], "staged_only")

    def test_review_console_stage_apply_splits_review_inbox_by_route(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            console_dir = root / "data/review_console"
            console_dir.mkdir(parents=True)
            (root / "data/review_inbox.json").write_text(
                json.dumps(
                    {
                        "items": [
                            {
                                "inbox_id": "inbox_future",
                                "kind": "current_year_confirmation",
                                "title": "丸の内de盆踊り",
                                "source_id": "official_source",
                                "source_key": "marunouchi|2026",
                                "recommended_action": "confirm_current_date",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            decisions_path = console_dir / "decisions.json"
            item_id = "review_inbox:inbox_future|official_source|marunouchi|2026"
            decisions_path.write_text(
                json.dumps(
                    {
                        "decisions": {
                            item_id: {
                                "item_id": item_id,
                                "source_id": "review_inbox",
                                "item_key": "inbox_future|official_source|marunouchi|2026",
                                "decision": "accept",
                                "decision_label": "レビュー採用",
                                "apply_value": "confirm_current_date",
                                "reviewer": "内田さん",
                                "updated_at": "2026-07-17T14:00:00+00:00",
                            }
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with patch.dict("os.environ", {data.REVIEW_CONSOLE_READER_MODE_ENV: "inbox"}):
                result = data.stage_apply(root=root, decisions_path=decisions_path, write=True)
            master_db_created = (root / "data/bon_odori_master.sqlite").exists()

        self.assertEqual(result["review_inbox_decision_count"], 1)
        self.assertEqual(result["staged_files"][0]["source_id"], "review_inbox:change_request")
        self.assertFalse(master_db_created)


if __name__ == "__main__":
    unittest.main()
