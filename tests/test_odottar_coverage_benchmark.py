import hashlib
import json
from pathlib import Path
from datetime import date
import subprocess
import sys

import pytest

from build_odottar_coverage_benchmark import SAFETY_BOUNDARY, append_history, build_report, match_score, render_markdown


ROOT = Path(__file__).resolve().parents[1]


def test_report_hashes_raw_bytes_and_never_creates_candidates() -> None:
    raw = '[{"eid":"o1","name":"A盆踊り","venue":"V","area":"江戸川区","start":"2026-08-01"}]'.encode()
    report = build_report(
        raw,
        json.loads(raw),
        [{"name": "A盆踊り", "venue": "V", "area": "江戸川区", "date": "2026-08-01"}],
        fetched_at="2026-08-24T00:00:00Z",
        source_url="https://odottar.com/events.json",
        as_of="2026-08-01",
    )
    assert report["source"]["raw_sha256"] == hashlib.sha256(raw).hexdigest()
    assert report["canonical_write_count"] == 0
    assert report["review_inbox_candidate_count"] == 0
    assert report["safety_boundary"] == SAFETY_BOUNDARY
    assert {key: report["summary"][key] for key in ("odottar_tokyo23", "bonsuke_tokyo23", "estimated_matched", "odottar_only", "bonsuke_only")} == {
        "odottar_tokyo23": 1,
        "bonsuke_tokyo23": 1,
        "estimated_matched": 1,
        "odottar_only": 0,
        "bonsuke_only": 0,
    }


def test_match_requires_compatible_area_and_reports_coverage_gap() -> None:
    rows = [
        {"eid": "o1", "name": "中央盆踊り", "venue": "同じ公園", "area": "江戸川区", "start": "2026-08-01"},
        {"eid": "o2", "name": "未掲載盆踊り", "venue": "別公園", "area": "江戸川区", "start": "2026-08-02"},
    ]
    bonsuke = [{"name": "中央盆踊り", "venue": "同じ公園", "area": "葛飾区", "date": "2026-08-01"}]
    raw = json.dumps(rows, ensure_ascii=False).encode()
    report = build_report(raw, rows, bonsuke, fetched_at="2026-08-24T00:00:00Z", source_url="test", as_of="2026-08-01")
    assert report["summary"]["estimated_matched"] == 0
    assert report["summary"]["odottar_only"] == 2
    assert report["summary"]["bonsuke_only"] == 1


def test_workflow_archives_raw_but_commits_only_metrics() -> None:
    text = (ROOT / ".github/workflows/odottar-coverage-benchmark.yml").read_text(encoding="utf-8")
    assert "https://odottar.com/events.json" in text
    assert "${{ runner.temp }}/odottar-events.json" in text
    assert "git add data/odottar_coverage_latest.json" in text
    assert "git add data/odottar_coverage_history.json" in text
    assert "git add data/public/events_public.json" not in text
    assert "review_inbox" not in text
    assert "apply_" not in text


def odo(eid="o1", start="2026-10-20", end=None, **fields):
    return {"eid": eid, "name": "中央盆踊り", "venue": "中央公園", "area": "中央区", "start": start, "end": end, **fields}


def bon(occurrence_id="b1", day="2026-10-20", end=None, **fields):
    return {"occurrence_id": occurrence_id, "name": "中央盆踊り", "venue": "中央公園", "area": "中央区", "date": day, "date_end": end,
            "current_event_state": "confirmed", "date_certainty_tier": "confirmed", **fields}


def report(odottar=(), bonsuke=(), **kwargs):
    rows = list(odottar)
    raw = json.dumps(rows, ensure_ascii=False).encode()
    options = {"fetched_at": "2026-10-18T00:00:00Z", "source_url": "synthetic-only", "as_of": "2026-10-18"}
    options.update(kwargs)
    return build_report(raw, rows, list(bonsuke), **options)


@pytest.mark.parametrize("day,included", [("2026-10-17", False), ("2026-10-18", True), ("2026-11-16", True), ("2026-11-17", False)])
def test_window_includes_as_of_and_last_day_but_excludes_next_midnight(day, included):
    value = report([odo(start=day)], [bon(day=day)])
    assert value["window"] == {"as_of": "2026-10-18", "start_inclusive": "2026-10-18", "end_exclusive": "2026-11-17", "last_inclusive": "2026-11-16", "days": 30, "timezone": "Asia/Tokyo"}
    assert value["summary"]["odottar_tokyo23"] == value["summary"]["bonsuke_tokyo23"] == int(included)


def test_aware_timestamps_use_jst_and_naive_dates_are_jst():
    value = report([odo(start="2026-10-17T15:00:00Z"), odo("o2", start="2026-11-16T15:00:00Z")],
                   [bon(day="2026-10-18T00:00:00")], as_of="2026-10-17T15:00:00Z")
    assert value["window"]["start_inclusive"] == "2026-10-18"
    assert value["summary"]["odottar_tokyo23"] == value["summary"]["bonsuke_tokyo23"] == 1
    assert value["summary"]["estimated_matched"] == 1


def test_window_crosses_year_boundary_and_clips_continuous_ranges():
    value = report([odo(start="2026-12-30", end="2027-01-03")], [bon(day="2026-12-31", end="2027-01-03")],
                   as_of=date(2026, 12, 31), days=3)
    assert value["window"]["end_exclusive"] == "2027-01-03"
    assert value["summary"]["odottar_dance_days"] == value["summary"]["bonsuke_dance_days"] == 3
    assert value["summary"]["estimated_matched_dance_days"] == 3


def test_multiday_and_noncontiguous_listings_union_dates_without_inflation():
    rows = [odo(start="2026-10-17", end="2026-10-20"), odo(start="2026-10-20"),
            odo(start="2026-10-25"), odo(start="2026-10-25")]
    value = report(rows, [bon(day="2026-10-19", end="2026-10-20"), bon(day="2026-10-20")])
    assert value["summary"]["odottar_tokyo23"] == value["summary"]["bonsuke_tokyo23"] == 1
    assert value["summary"]["odottar_dance_days"] == 4
    assert value["summary"]["bonsuke_dance_days"] == 2
    assert value["summary"]["estimated_matched_dance_days"] == 2
    assert value["input_quality"]["odottar"]["coalesced_listing_rows"] == 3


def test_exact_duplicates_without_ids_are_removed_and_different_events_stay_distinct():
    first = odo()
    first.pop("eid")
    other = {**first, "venue": "別の公園"}
    value = report([first, dict(first), other], [bon("b1"), bon("b2", venue="別の公園")])
    assert value["summary"]["odottar_tokyo23"] == value["summary"]["bonsuke_tokyo23"] == 2
    assert value["summary"]["odottar_dance_days"] == 2
    assert value["summary"]["estimated_matched"] == 2
    # Even identical names, venues and dates do not override distinct stable IDs.
    assert report([odo("o1"), odo("o2")])["summary"]["odottar_tokyo23"] == 2


def test_conflicting_source_id_locations_are_held_out_instead_of_merged():
    value = report([odo(), odo(venue="別の公園")])
    assert value["summary"]["odottar_tokyo23"] == 0
    assert value["input_quality"]["odottar"]["identity_conflict_groups"] == 1


def test_same_titles_alone_and_nonoverlapping_dates_cannot_match():
    assert match_score(odo(), bon(venue="全く違う神社")) is None
    assert match_score(odo(), bon(day="2026-10-21")) is None
    assert match_score(odo(venue=""), bon(venue="")) is None


def test_workshops_are_separate_from_festivals_and_unclassified_names():
    value = report([odo("festival"), odo("lesson", name="盆踊り講習会", end="2026-10-21"),
                    odo("lesson", name="盆踊り講習会", start="2026-10-21"), odo("other", name="親睦会")],
                   [bon("lesson", name="盆踊り練習会")])
    assert value["summary"]["odottar_tokyo23"] == 1
    assert value["summary"]["bonsuke_tokyo23"] == 0
    workshops = value["separate_counts"]["workshop"]["scheduled_or_listed"]
    assert workshops["odottar_tokyo23"] == workshops["bonsuke_tokyo23"] == 1
    assert workshops["odottar_event_days"] == 2
    assert value["separate_counts"]["unclassified"]["scheduled_or_listed"]["odottar_tokyo23"] == 1


def test_historical_references_are_not_slid_and_predictions_stay_separate():
    rows = [bon("past", day="2025-10-20", current_event_state="predicted", date_certainty_tier="historical_reference", hints=[[10, 20]]),
            bon("forecast", day="2025-10-20", current_event_state="predicted", date_certainty_tier="historical_slide", predicted_date="2026-10-20", predicted_date_end="2026-10-21"),
            bon("season", day=None, current_event_state="predicted", date_certainty_tier="season_hint", months=[10]),
            bon("cancelled", current_event_state="cancelled"), bon("ended", current_event_state="ended")]
    value = report([odo()], rows)
    assert value["summary"]["bonsuke_tokyo23"] == 0
    uncertain = value["separate_counts"]["festival"]["uncertain"]
    assert uncertain["bonsuke_events"] == 1 and uncertain["bonsuke_projected_days"] == 2
    assert value["headline_certainty"]["odottar"] == {"confirmed": 0, "listed": 1}
    assert value["input_quality"]["bonsuke"]["historical_without_forward_date_rows"] == 2
    assert value["input_quality"]["bonsuke"]["excluded_status_rows"] == 2


def test_prediction_dict_and_legacy_category_do_not_promote_forecasts():
    row = bon(day="2025-10-20", public_category="recurring_last_year", current_event_state=None, date_certainty_tier=None,
              date_prediction={"date": "2026-10-20", "date_end": "2026-10-20"})
    value = report([], [row])
    assert value["summary"]["bonsuke_tokyo23"] == 0
    assert value["separate_counts"]["festival"]["uncertain"]["bonsuke_events"] == 1


def test_mixed_certainty_in_one_identity_never_promotes_predicted_dates():
    value = report([], [bon(), bon(day=None, current_event_state="predicted", date_certainty_tier="rule_predicted", predicted_date="2026-10-21")])
    assert value["summary"]["bonsuke_tokyo23"] == 0
    assert value["input_quality"]["bonsuke"]["mixed_certainty_groups"] == 1
    assert value["separate_counts"]["festival"]["uncertain"]["bonsuke_projected_days"] == 2


def test_invalid_ranges_and_non_wards_are_diagnosed_not_collapsed_to_one_day():
    value = report([odo("bad", start="invalid"), odo("reverse", end="2026-10-19"),
                    odo("long", start="2026-01-01", end="2027-02-01"), odo("outside", area="横浜市"),
                    odo("tokyo", area="東京都中央区")])
    assert value["summary"]["odottar_tokyo23"] == 1
    assert value["input_quality"]["odottar"]["missing_or_invalid_date_rows"] == 3
    assert value["input_quality"]["odottar"]["outside_tokyo23_rows"] == 1


def test_stale_snapshot_is_not_presented_as_current_or_confirmation_evidence():
    value = report([odo()], [bon()], fetched_at="2026-09-14T00:08:55Z")
    assert value["freshness"]["odottar"]["status"] == "stale"
    assert value["freshness"]["odottar"]["age_days_at_as_of"] == 34
    assert value["freshness"]["bonsuke"]["status"] == "unknown"
    markdown = render_markdown(value)
    assert "2026-09-14T00:08:55Z" in markdown
    assert "現在の網羅性と断定できません" in markdown
    assert "確認状態は不明" in markdown
    assert value["canonical_write_count"] == value["review_inbox_candidate_count"] == 0


@pytest.mark.parametrize("options", [{"as_of": "invalid"}, {"days": 0}, {"days": -1}, {"days": 367}])
def test_invalid_window_is_rejected(options):
    with pytest.raises(ValueError):
        report(**options)


def test_history_preserves_legacy_unbounded_results_and_separate_windows(tmp_path):
    path = tmp_path / "history.json"
    legacy = {"fetched_at": "2026-09-14T00:08:55Z", "raw_sha256": "legacy", "odottar_tokyo23": 785}
    path.write_text(json.dumps({"schema_version": 1, "snapshots": [legacy]}))
    first = report([odo()])
    append_history(path, first)
    append_history(path, first)
    append_history(path, report([odo()], as_of="2026-10-19"))
    value = json.loads(path.read_text())
    assert value["schema_version"] == 2
    assert len(value["snapshots"]) == 3
    assert legacy in value["snapshots"]


def test_cli_uses_injected_window_and_unknown_freshness_without_touching_inputs(tmp_path):
    odo_path, bon_path = tmp_path / "odottar.json", tmp_path / "bonsuke.json"
    odo_raw = json.dumps([odo()]).encode()
    bon_raw = json.dumps([bon()]).encode()
    odo_path.write_bytes(odo_raw)
    bon_path.write_bytes(bon_raw)
    out_json, out_md, history = [tmp_path / name for name in ("report.json", "report.md", "history.json")]
    result = subprocess.run([sys.executable, str(ROOT / "build_odottar_coverage_benchmark.py"), "--odottar-json", str(odo_path), "--bonsuke-json", str(bon_path),
                             "--as-of", "2026-10-18", "--out-json", str(out_json), "--out-md", str(out_md), "--history", str(history)], cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    value = json.loads(out_json.read_text())
    assert value["fetched_at"] is None
    assert value["freshness"]["odottar"]["status"] == value["freshness"]["bonsuke"]["status"] == "unknown"
    assert value["window"]["end_exclusive"] == "2026-11-17"
    assert value["bonsuke_source"]["raw_sha256"] == hashlib.sha256(bon_raw).hexdigest()
    assert odo_path.read_bytes() == odo_raw and bon_path.read_bytes() == bon_raw
