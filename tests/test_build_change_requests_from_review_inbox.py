import unittest

from report_apply.apply_change_requests import validate_payload
from review_inbox_adapters.build_change_requests_from_review_inbox import (
    build_requests,
    clean_event_name_for_match,
    parse_event_date_text,
)


def official_source_item(
    inbox_id="inbox_test",
    event_name="団体名「イベント名」",
    venue="テスト会場",
    event_year=2026,
    event_date_text="2026 [X1]\n7/19",
    source_url="https://example.city.lg.jp/event",
):
    return {
        "inbox_id": inbox_id,
        "kind": "official_source",
        "title": event_name,
        "event_name": event_name,
        "venue": venue,
        "event_year": event_year,
        "source_url": source_url,
        "payload": {
            "event_date_text": event_date_text,
            "source_url": source_url,
            "memo": event_name,
        },
    }


def staged_row(source_item, change_type, note=""):
    return {
        "inbox_update": {"inbox_id": source_item["inbox_id"], "decision_route": "change_request"},
        "apply_value": "confirm_current_date",
        "note": note,
        "source_item": source_item,
        "change_type": change_type,
    }


class CleanEventNameTests(unittest.TestCase):
    def test_extracts_bracketed_name_over_organizer_prefix(self):
        self.assertEqual(
            clean_event_name_for_match("新井町会連合会・中野通り桜まつり実行委員会「中野通り桜まつり」"),
            "中野通り桜まつり",
        )

    def test_normalizes_halfwidth_brackets(self):
        self.assertEqual(
            clean_event_name_for_match("大蔵本村睦会 ｢盆踊り大会｣ 7月20日(日)午後7時-"),
            "盆踊り大会",
        )

    def test_strips_unmatched_opening_bracket(self):
        self.assertEqual(
            clean_event_name_for_match("「葛飾菖蒲まつり 水元公園会場 民踊パレード 5月31日(日)。"),
            "葛飾菖蒲まつり 水元公園会場 民踊パレード",
        )

    def test_falls_back_to_schedule_stripping_without_brackets(self):
        self.assertEqual(
            clean_event_name_for_match("鎌田協和会 鎌田納涼盆踊り 7月26日(土) 18:30-。"),
            "鎌田協和会 鎌田納涼盆踊り",
        )

    def test_returns_original_when_name_only(self):
        self.assertEqual(clean_event_name_for_match("奥沢交和会"), "奥沢交和会")


class ParseEventDateTextTests(unittest.TestCase):
    def test_single_day(self):
        self.assertEqual(parse_event_date_text("2026 [V1]\n5/31"), ("2026-05-31", "2026-05-31"))

    def test_date_range(self):
        self.assertEqual(parse_event_date_text("2025 [L19]\n7/26 - 27"), ("2025-07-26", "2025-07-27"))

    def test_missing_text_returns_none(self):
        self.assertEqual(parse_event_date_text(""), (None, None))

    def test_invalid_calendar_date_returns_none(self):
        self.assertEqual(parse_event_date_text("2026 [Z1]\n2/30"), (None, None))


class BuildRequestsTests(unittest.TestCase):
    def test_confirm_current_year_date_success(self):
        item = official_source_item()
        requests, unresolved = build_requests(
            [staged_row(item, "confirm_current_year_date")], current_year=2026
        )
        self.assertEqual(unresolved, [])
        self.assertEqual(len(requests), 1)
        request = requests[0]
        self.assertEqual(request["change_type"], "confirm_current_year_date")
        self.assertEqual(request["date_start"], "2026-07-19")
        self.assertEqual(request["date_end"], "2026-07-19")
        self.assertEqual(request["match_hint"]["event_name_hint"], "イベント名")
        self.assertEqual(request["match_hint"]["venue_name_hint"], "テスト会場")
        self.assertNotIn("venue", request)

    def test_confirm_current_year_date_range_keeps_distinct_end(self):
        item = official_source_item(event_date_text="2026 [P2]\n6/5 - 6")
        requests, unresolved = build_requests(
            [staged_row(item, "confirm_current_year_date")], current_year=2026
        )
        self.assertEqual(unresolved, [])
        self.assertEqual(requests[0]["date_start"], "2026-06-05")
        self.assertEqual(requests[0]["date_end"], "2026-06-06")

    def test_confirm_current_year_date_rejects_non_current_year(self):
        item = official_source_item(event_date_text="2025 [L3]\n7/19")
        requests, unresolved = build_requests(
            [staged_row(item, "confirm_current_year_date")], current_year=2026
        )
        self.assertEqual(requests, [])
        self.assertEqual(len(unresolved), 1)
        self.assertTrue(unresolved[0]["reason"].startswith("event_date_not_in_current_year"))

    def test_confirm_current_year_date_reports_unparseable_date(self):
        item = official_source_item(event_date_text="日程未定")
        requests, unresolved = build_requests(
            [staged_row(item, "confirm_current_year_date")], current_year=2026
        )
        self.assertEqual(requests, [])
        self.assertEqual(unresolved[0]["reason"], "date_parse_failed")

    def test_add_historical_reference_success(self):
        item = official_source_item(event_year=2025, event_date_text="2025 [L3]\n7/19")
        requests, unresolved = build_requests(
            [staged_row(item, "add_historical_reference")], current_year=2026
        )
        self.assertEqual(unresolved, [])
        request = requests[0]
        self.assertEqual(request["change_type"], "add_historical_reference")
        self.assertEqual(request["historical_year"], 2025)
        self.assertEqual(request["historical_date"], "2025-07-19")
        self.assertEqual(request["event_year"], 2026)

    def test_add_historical_reference_rejects_same_or_future_year(self):
        item = official_source_item(event_year=2026, event_date_text="2026 [L3]\n7/19")
        requests, unresolved = build_requests(
            [staged_row(item, "add_historical_reference")], current_year=2026
        )
        self.assertEqual(requests, [])
        self.assertTrue(unresolved[0]["reason"].startswith("historical_year_not_before_current_year"))

    def test_update_venue_success(self):
        item = official_source_item()
        requests, unresolved = build_requests(
            [staged_row(item, "update_venue")], current_year=2026
        )
        self.assertEqual(unresolved, [])
        self.assertEqual(requests[0]["venue"], {"name": "テスト会場"})

    def test_update_venue_requires_venue_text(self):
        item = official_source_item(venue="")
        requests, unresolved = build_requests(
            [staged_row(item, "update_venue")], current_year=2026
        )
        self.assertEqual(requests, [])
        self.assertEqual(unresolved[0]["reason"], "missing_venue")

    def test_unsupported_change_type_is_reported(self):
        item = official_source_item()
        requests, unresolved = build_requests(
            [staged_row(item, "create_current_year_occurrence")], current_year=2026
        )
        self.assertEqual(requests, [])
        self.assertEqual(unresolved[0]["reason"], "unsupported_change_type:create_current_year_occurrence")

    def test_duplicate_inbox_id_is_reported_once(self):
        item = official_source_item()
        row = staged_row(item, "confirm_current_year_date")
        requests, unresolved = build_requests([row, row], current_year=2026)
        self.assertEqual(len(requests), 1)
        self.assertEqual(len(unresolved), 1)
        self.assertEqual(unresolved[0]["reason"], "duplicate_request_id")

    def test_occurrence_id_hint_is_used_when_present(self):
        item = official_source_item()
        item["payload"]["observed_candidate"] = {
            "candidate_key": "occ_abc123|2026-07-19||",
        }
        requests, _ = build_requests(
            [staged_row(item, "confirm_current_year_date")], current_year=2026
        )
        self.assertEqual(requests[0]["occurrence_id"], "occ_abc123")

    def test_built_requests_pass_apply_change_requests_schema_validation(self):
        confirm_item = official_source_item(inbox_id="inbox_confirm")
        historical_item = official_source_item(
            inbox_id="inbox_hist", event_year=2025, event_date_text="2025 [L3]\n7/19"
        )
        venue_item = official_source_item(inbox_id="inbox_venue")
        requests, unresolved = build_requests(
            [
                staged_row(confirm_item, "confirm_current_year_date"),
                staged_row(historical_item, "add_historical_reference"),
                staged_row(venue_item, "update_venue"),
            ],
            current_year=2026,
        )
        self.assertEqual(unresolved, [])
        payload = {"request_type": "rdb_change_requests", "requests": requests}
        # Raises ValueError on failure; a clean return means the schema is valid.
        validate_payload(payload)


if __name__ == "__main__":
    unittest.main()
