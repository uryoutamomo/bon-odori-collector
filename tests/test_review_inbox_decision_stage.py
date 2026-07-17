import json
import tempfile
import unittest
from pathlib import Path

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


class ReviewInboxDecisionStageTest(unittest.TestCase):
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
                        apply_value="publish_song",
                        inbox_id="inbox_song",
                        kind="song",
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

            result = data.stage_apply(root=root, decisions_path=decisions_path, write=True)
            master_db_created = (root / "data/bon_odori_master.sqlite").exists()

        self.assertEqual(result["review_inbox_decision_count"], 1)
        self.assertEqual(result["staged_files"][0]["source_id"], "review_inbox:change_request")
        self.assertFalse(master_db_created)


if __name__ == "__main__":
    unittest.main()
