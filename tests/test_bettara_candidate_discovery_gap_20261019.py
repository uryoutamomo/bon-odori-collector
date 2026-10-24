"""Nonproduction discovery-gap fixture; no actual page fetch or registry edit."""

import json

import pytest

from review_inbox_adapters.official_source_adapter import WardOfficialSourceAdapter
from review_inbox_adapters.source_adapter import adapt_source_payload
from scan_ward_official_sources import DEFAULT_REGISTRY, load_registry, scan_registry


def test_tourism_page_is_not_admitted_by_the_ward_domain_gate(tmp_path):
    registry = tmp_path / "synthetic-registry.json"
    registry.write_text(json.dumps({
        "priority_wards": ["中央区"],
        "sources": [{"id": "synthetic-only", "ward": "中央区", "title": "合成fixture",
                     "url": "https://www.gotokyo.org/jp/spot/ev137/index.html"}],
    }))
    with pytest.raises(ValueError, match="not on an official ward domain"):
        load_registry(registry)


def test_mixed_market_programme_uses_only_the_explicit_bon_dance_date_and_hours():
    # Use an already registered ward source; this does not register GO TOKYO or
    # claim that this synthetic market is a real event on that ward's website.
    source = load_registry(DEFAULT_REGISTRY)[0]
    raw = """<ul><li>合成の秋の市：2026年10月19日・20日 10:00〜21:00<br>
    盆踊り：2026年10月20日 16:30〜19:30（20日のみ）<br>会場：区内公園
    </li></ul>"""

    def fake_scan(target, year, **_kwargs):
        return [{"status": "confirmed", "source_url": source["url"], "title": "合成fixture",
                 "detected_dates": ["2026-10-19", "2026-10-20"]}]

    rows, _reports = scan_registry([source], 2026, scan_fn=fake_scan,
                                  html_fetch_fn=lambda _url, **_kwargs: raw)
    row, = rows
    assert row["parse_mode"] == "html_list_item"
    programme_date = row["event_date_text"]
    assert "10月20日" in programme_date and "10月19日" not in programme_date, programme_date
    assert "16:30" in programme_date and "19:30" in programme_date, programme_date
    assert "10:00" not in programme_date and "21:00" not in programme_date, programme_date
    assert row["schedule_review_status"] == "explicit"
    assert row["schedule_scope"] == "bon_odori"
    assert row["decision"] == "pending"
    assert row["source_url"] == source["url"]
    assert row["source_registry_id"] == source["id"]
    assert "10月19日" in row["memo"]  # Preserve original context, not as dance facts.


def scan_fixture(raw, *, evidence_text="", detected_dates=None):
    source = load_registry(DEFAULT_REGISTRY)[0]
    scanned = [{"status": "confirmed", "source_url": source["url"], "title": "合成fixture",
                "detected_dates": detected_dates or ["2026-10-19", "2026-10-20"],
                "evidence": {"text": evidence_text}}]
    rows, reports = scan_registry([source], 2026, scan_fn=lambda *_args, **_kwargs: scanned,
                                  html_fetch_fn=lambda *_args, **_kwargs: raw)
    return rows, reports, source


@pytest.mark.parametrize("programme", [
    "盆踊り：開催日は後日案内、16:30〜19:30",
    "盆踊り：16:30〜19:30",
    "盆踊り：20日16:30〜19:30",
    "盆踊り：10月20日または10月21日16:30〜19:30",
    "盆踊り：10月20日16:30〜19:30、17:00〜20:00",
    "盆踊り：10月20日16:30〜24:00",
    "盆踊り：2025年10月20日16:30〜19:30",
    "盆踊りは10月20日ではありません",
])
def test_ambiguous_or_withheld_programme_is_held_without_page_date_fallback(programme):
    raw = f"<ul><li>市全体：10月19日・20日10:00〜21:00<br>{programme}</li></ul>"
    rows, reports, source = scan_fixture(raw)
    row, = rows
    assert row["decision"] == "pending"
    assert row["event_date_text"] == ""
    assert row["schedule_review_status"] == "ambiguous"
    assert row["source_registry_id"] == source["id"]
    assert "10月19日" in row["memo"]
    assert reports[0]["structured_candidate_count"] == 1
    assert reports[0]["page_fallback_count"] == 0
    assert reports[0]["ambiguous_schedule_count"] == 1
    item, = adapt_source_payload(WardOfficialSourceAdapter(2026), {"rows": rows})
    assert item["recommended_action"] == "review_official_source"
    assert item["payload"]["decision"] == "pending"
    assert item["payload"]["event_date_text"] == ""
    assert item["payload"]["schedule_review_status"] == "ambiguous"
    assert "status" not in item


@pytest.mark.parametrize("programme,expected,status", [
    ("盆踊り：10月20日16:30〜19:30", "10月20日 / 16:30〜19:30", "explicit"),
    ("盆踊り：10月20日", "10月20日", "date_only"),
    ("盆踊り：日程調整中", "", "ambiguous"),
])
def test_page_fallback_scopes_evidence_instead_of_using_detected_market_dates(programme, expected, status):
    rows, reports, source = scan_fixture("<p>構造化できない合成本文</p>",
        evidence_text=f"市全体：10月19日・20日10:00〜21:00。{programme}")
    row, = rows
    assert row["event_date_text"] == expected
    assert row["schedule_review_status"] == status
    assert row["decision"] == "pending"
    assert row["source_url"] == source["url"]
    assert reports[0]["page_fallback_count"] == 1
    assert reports[0]["ambiguous_schedule_count"] == int(status == "ambiguous")


@pytest.mark.parametrize("programme,expected,status", [
    ("秋の市（盆踊り：10月20日16:30〜19:30）", "10月20日 / 16:30〜19:30", "explicit"),
    ("秋の市（盆踊り：10月20日）", "10月20日", "date_only"),
    ("秋の市（盆踊り：日時は後日案内）", "", "ambiguous"),
])
def test_mixed_table_cannot_override_programme_with_market_columns(programme, expected, status):
    raw = f"""<table><tr><th>開催日</th><th>時間</th><th>行事名</th><th>会場</th></tr>
    <tr><td>10月19日・20日</td><td>10:00〜21:00</td><td>{programme}</td><td>区内公園</td></tr></table>"""
    rows, reports, _source = scan_fixture(raw)
    row, = rows
    assert row["event_date_text"] == expected
    assert row["schedule_review_status"] == status
    assert reports[0]["page_fallback_count"] == 0


def test_ordinary_single_event_list_table_and_fallback_keep_their_dates():
    cases = [
        ("<ul><li>8月3日 町会盆踊り 東公園</li><li>盆踊り会場案内</li></ul>", "8月3日", 0),
        ("<table><tr><th>開催日</th><th>時間</th><th>行事名</th><th>場所</th></tr>"
         "<tr><td>8月3日</td><td>18時</td><td>町会盆踊り</td><td>東公園</td></tr></table>", "8月3日 / 18時", 0),
        ("<p>合成の単独告知</p>", "2026-08-03", 1),
    ]
    for raw, expected, fallback_count in cases:
        rows, reports, _source = scan_fixture(raw, evidence_text="8月3日 町会盆踊り 東公園", detected_dates=["2026-08-03"])
        row, = rows
        assert row["event_date_text"] == expected
        assert row["decision"] == "pending"
        assert "schedule_scope" not in row
        assert reports[0]["page_fallback_count"] == fallback_count
        assert reports[0]["ambiguous_schedule_count"] == 0
