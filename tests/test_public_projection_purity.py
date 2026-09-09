import copy
import json
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest

from export_public_events import project_public_events, write_public_projection
from public_export_support.projection_inputs import PublicProjectionInputs, fixed_date_rules_from_payload


def event(**changes):
    row = {
        "name": "町会盆踊り", "venue": "中央公園", "area": "中央区",
        "name_confirmed": True, "date": "2026-08-15", "date_end": "2026-08-16",
        "status": "確定", "months": [8], "detail": "地域の盆踊り。",
        "source_urls": [], "songs": [{"name": "東京音頭", "confidence": "hint"}],
        "_occurrence_id": "occ_1", "_series_id": "ser_1", "_venue_id": "ven_1",
        "_event_year": 2026,
    }
    row.update(changes)
    return row


def inputs():
    return PublicProjectionInputs(prediction_payload={}, overrides={}, fixed_date_rules={})


def test_projection_performs_no_io_and_preserves_all_inputs():
    rows = [event(), event(name="恒例夏祭り", date="2025-08-15", date_end="2025-08-16")]
    values = inputs()
    before = copy.deepcopy((rows, values))
    with ExitStack() as stack:
        for target in ("builtins.open", "pathlib.Path.open", "sqlite3.connect",
                       "urllib.request.urlopen", "os.getenv"):
            stack.enter_context(patch(target, side_effect=AssertionError("projection attempted I/O")))
        stack.enter_context(patch.dict("os.environ", {"BON_ODORI_PUBLIC_TODAY": "1900-01-01"}))
        result = project_public_events(rows, target_year=2026, today="2026-08-16", inputs=values)
        again = project_public_events(rows, target_year=2026, today="2026-08-16", inputs=values)
    assert result == again
    assert (rows, values) == before
    result["public_events"][0]["songs"][0]["name"] = "changed"
    assert (rows, values) == before


@pytest.mark.parametrize("today", [None, "", "not-a-date", "2026-02-30"])
def test_pure_projection_rejects_missing_date_even_with_environment(today):
    with patch.dict("os.environ", {"BON_ODORI_PUBLIC_TODAY": "2026-09-09"}):
        with pytest.raises(ValueError, match="today is required"):
            project_public_events([event()], target_year=2026, today=today, inputs=inputs())


def test_projection_consumes_explicit_prediction_and_override_without_aliasing():
    values = PublicProjectionInputs(
        prediction_payload={"predictions": [{
            "event_name": "町会盆踊り", "venue": "中央公園", "target_year": 2026,
            "actual_observations": [{"year": 2025}],
            "prediction": {
                "predicted_date_start": "2026-08-15", "predicted_date_end": "2026-08-16",
                "predicted_weekday_start": "土", "predicted_weekday_end": "日",
                "confidence": "high", "score": 0.8, "rule_type": "fixed",
                "basis": "主催者ルール", "evidence_years": [2024, 2025], "evidence_count": 2,
            },
        }]},
        overrides={"overrides": [{"match": {"name": "町会盆踊り"}, "set": {"detail": "確認済みの紹介文"}}]},
        fixed_date_rules={},
    )
    before = copy.deepcopy(values)
    result = project_public_events(
        [event(date="2025-08-15", date_end="2025-08-16")],
        target_year=2026, today="2026-08-01", inputs=values,
    )
    projected = result["public_events"][0]
    assert projected["detail"] == "確認済みの紹介文"
    assert projected["date"] == "2025-08-15"
    assert projected["predicted_date"] == "2026-08-15"
    assert projected["date_certainty_tier"] == "rule_predicted"
    projected["date_prediction"]["evidence_years"].append(1900)
    result["prediction_report"]["applied"][0]["date_prediction"]["evidence_years"].append(1901)
    assert values == before


@pytest.mark.parametrize("today,category", [
    ("2026-08-15", "upcoming"), ("2026-08-16", "upcoming"), ("2026-08-17", "ended"),
])
def test_end_date_remains_inclusive_for_derived_axes(today, category):
    result = project_public_events([event()], target_year=2026, today=today, inputs=inputs())
    assert result["public_events"][0]["public_category"] == category
    assert result["public_events"][0]["date"] == "2026-08-15"


@pytest.mark.parametrize("today,has_slide", [
    ("2026-08-14", True), ("2026-08-15", True), ("2026-08-16", False),
])
def test_historical_slide_preserves_existing_start_date_expiry(today, has_slide):
    # The legacy contract expires at the projected start, even for a multi-day event.
    values = inputs()
    values.fixed_date_rules.update(fixed_date_rules_from_payload({"rules": [{
        "name": "町会盆踊り", "venue": "中央公園", "month": 8, "day": 15,
        "end_month": 8, "end_day": 17, "source_url": "https://example.jp/official",
    }]}))
    result = project_public_events(
        [event(date="2025-08-15", date_end="2025-08-17")],
        target_year=2026, today=today, inputs=values,
    )["public_events"][0]
    assert ("historical_slide" in result) == has_slide
    assert result["date"] == "2025-08-15"
    assert result["current_event_state"] == "predicted"


def test_year_change_is_explicit_and_does_not_confirm_historical_dates():
    rows = [event(date="2026-12-31", date_end="2026-12-31", months=[12])]
    fixed_year = project_public_events(rows, target_year=2026, today="2027-01-01", inputs=inputs())
    next_year = project_public_events(rows, target_year=2027, today="2027-01-01", inputs=inputs())
    assert fixed_year["public_events"][0]["public_category"] == "ended"
    assert next_year["public_events"][0]["public_category"] == "recurring_last_year"
    assert next_year["public_events"][0]["date"] == "2026-12-31"
    assert next_year["public_events"][0]["display_tier"] != "confirmed"


def test_writer_uses_computed_four_artifacts_without_loading_sources():
    projection = project_public_events([event()], target_year=2026, today="2026-08-16", inputs=inputs())
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        with patch("export_public_events.load_public_projection_inputs", side_effect=AssertionError("read")):
            write_public_projection(
                projection, out_dir=root / "public", source_map_path=root / "source_map.json",
                prediction_report_path=root / "prediction.json",
                series_split_json_path=root / "series.json", series_split_md_path=root / "series.md",
            )
        body = (root / "public/events_public.json").read_text()
        js = (root / "public/events_public.js").read_text()
        assert js == "// Auto-generated by export_public_events.py. Do not edit by hand.\nconst EVENTS = " + body + ";\n"
        assert json.loads(body) == projection["public_events"]
        assert json.loads((root / "public/event_songs_public.json").read_text()) == projection["song_rows"]
        assert json.loads((root / "source_map.json").read_text()) == projection["source_map"]
