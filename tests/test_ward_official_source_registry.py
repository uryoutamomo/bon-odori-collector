import json
from pathlib import Path

from review_inbox_adapters.official_source_adapter import WardOfficialSourceAdapter
from review_inbox_adapters.source_adapter import adapt_source_payload
from scan_ward_official_sources import (
    SAFETY_BOUNDARY,
    extract_structured_event_rows,
    load_registry,
    scan_registry,
)


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "data/ward_official_source_registry.json"


def test_registry_seeds_exactly_the_eight_priority_wards_with_official_urls() -> None:
    payload = json.loads(REGISTRY.read_text(encoding="utf-8"))
    assert set(payload["priority_wards"]) == {"江戸川区", "足立区", "板橋区", "葛飾区", "大田区", "豊島区", "荒川区", "練馬区"}
    sources = load_registry(REGISTRY)
    assert len(sources) >= 16
    assert set(row["ward"] for row in sources) == set(payload["priority_wards"])


def test_scanner_reuses_proactive_scan_and_routes_only_confirmed_rows() -> None:
    source = load_registry(REGISTRY)[:1]
    calls = []

    def fake_scan(target, year, timeout, max_links_per_source):
        calls.append((target, year, timeout, max_links_per_source))
        return [
            {"status": "confirmed", "source_url": "https://www.city.edogawa.tokyo.jp/event.html", "title": "盆踊り", "detected_dates": ["2026-08-01"], "evidence": {"text": "公式一覧"}},
            {"status": "unconfirmed", "source_url": "https://www.city.edogawa.tokyo.jp/other.html", "title": "別ページ"},
        ]

    rows, reports = scan_registry(source, 2026, scan_fn=fake_scan, html_fetch_fn=lambda url, timeout: "<html></html>")
    assert len(calls) == 1
    assert calls[0][0]["official_sources"] == [source[0]["url"]]
    assert len(rows) == 1
    assert reports[0]["confirmed_count"] == 1
    assert rows[0]["decision"] == "pending"
    assert rows[0]["source_origin"] == "ward_official_source_registry"
    assert reports[0]["page_fallback_count"] == 1


def test_html_event_table_is_split_into_one_candidate_per_data_row() -> None:
    source = {
        "id": "adachi-bonfes-2026", "ward": "足立区", "title": "夏祭り・盆踊り",
        "url": "https://www.city.adachi.tokyo.jp/chiiki/bonfes2026.html",
        "source_type": "event_calendar", "format": "html_table", "priority": "high",
        "structured_extraction": "html_event_table",
    }
    raw = """
    <table><tr><th>開催日</th><th>開始時間</th><th>町会・自治会名（祭名称）</th><th>会場</th><th>住所</th></tr>
    <tr><td><p>7月10日</p><p>7月11日</p></td><td>18時</td><td>東淵江自治会<br>(納涼盆踊り大会)</td><td>稗田公園</td><td>東和5-9</td></tr>
    <tr><td>7月17日</td><td>18時30分</td><td>大谷田五丁目町会<br>(夏の祭典)</td><td>柳田公園</td><td>大谷田5-4-18</td></tr></table>
    """
    rows = extract_structured_event_rows(raw, source, source["url"], 2026)
    assert len(rows) == 2
    assert len({row["id"] for row in rows}) == 2
    assert rows[0]["event_name"] == "東淵江自治会 / (納涼盆踊り大会)"
    assert rows[0]["organizer"] == "東淵江自治会"
    assert rows[0]["festival_name"] == "納涼盆踊り大会"
    assert rows[0]["event_date_text"] == "7月10日 / 7月11日 / 18時"
    assert rows[0]["venue"] == "稗田公園"
    assert rows[0]["address"] == "東和5-9"
    assert rows[0]["parse_mode"] == "html_table_row"
    assert rows[1]["event_name"] == "大谷田五丁目町会 / (夏の祭典)"


def test_generic_table_requires_bon_context_per_row_and_list_items_are_supported() -> None:
    source = {
        "id": "generic", "ward": "江戸川区", "title": "行事一覧",
        "url": "https://www.city.edogawa.tokyo.jp/events.html",
        "source_type": "event_calendar", "format": "html", "priority": "high",
    }
    raw = """
    <table><tr><th>日程</th><th>行事名</th><th>場所</th></tr>
    <tr><td>8月1日</td><td>納涼盆踊り</td><td>中央公園</td></tr>
    <tr><td>8月2日</td><td>防災訓練</td><td>小学校</td></tr></table>
    <ul><li>8月3日 町会盆踊り 東公園</li><li>盆踊り会場案内</li></ul>
    """
    rows = extract_structured_event_rows(raw, source, source["url"], 2026)
    assert [row["parse_mode"] for row in rows] == ["html_table_row", "html_list_item"]
    assert all("防災訓練" not in row["event_name"] for row in rows)


def test_scan_registry_prefers_structured_rows_over_page_fallback() -> None:
    source = [{
        "id": "adachi-bonfes-2026", "ward": "足立区", "title": "夏祭り・盆踊り",
        "url": "https://www.city.adachi.tokyo.jp/chiiki/bonfes2026.html",
        "source_type": "event_calendar", "format": "html_table", "priority": "high",
        "structured_extraction": "html_event_table",
    }]

    def fake_scan(target, year, timeout, max_links_per_source):
        return [{"status": "confirmed", "source_url": source[0]["url"], "title": source[0]["title"]}]

    raw = "<table><tr><th>開催日</th><th>祭名称</th><th>会場</th></tr><tr><td>8月1日</td><td>町会夏祭り</td><td>公園</td></tr></table>"
    rows, reports = scan_registry(source, 2026, scan_fn=fake_scan, html_fetch_fn=lambda url, timeout: raw)
    assert len(rows) == 1
    assert rows[0]["parse_mode"] == "html_table_row"
    assert reports[0]["structured_candidate_count"] == 1
    assert reports[0]["page_fallback_count"] == 0


def test_ward_candidate_becomes_review_inbox_item_without_lifecycle_or_canonical_write() -> None:
    row = {
        "id": "ward-official-1", "decision": "pending", "suggested_source_type": "official",
        "suggested_score": 90, "source_url": "https://www.city.edogawa.tokyo.jp/event.html",
        "venue": "", "event_name": "盆踊り一覧", "region": "江戸川区", "event_year": 2026,
    }
    item = adapt_source_payload(WardOfficialSourceAdapter(2026), {"rows": [row]})[0]
    assert item["source_id"] == "ward_official_source"
    assert item["kind"] == "official_source"
    assert item["recommended_action"] == "review_official_source"
    assert item["payload"]["decision"] == "pending"
    assert "status" not in item and "decision" not in item
    assert SAFETY_BOUNDARY == "official-source review candidates only; no canonical or public event write"


def test_workflow_commits_candidates_and_adapted_snapshot_but_not_canonical_data() -> None:
    text = (ROOT / ".github/workflows/refresh_official_source_review.yml").read_text(encoding="utf-8")
    assert "python scan_ward_official_sources.py" in text
    assert "--ward-registry" in text
    assert "git add data/ward_official_source_candidates.json" in text
    assert "git add -f data/review_inbox_adapted/ward_official_source.json" in text
    assert "git add data/public/events_public.json" not in text
    assert "apply_change_requests.py" not in text
