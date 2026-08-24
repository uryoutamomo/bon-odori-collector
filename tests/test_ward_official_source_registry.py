import json
from pathlib import Path

from review_inbox_adapters.official_source_adapter import WardOfficialSourceAdapter
from review_inbox_adapters.source_adapter import adapt_source_payload
from scan_ward_official_sources import SAFETY_BOUNDARY, load_registry, scan_registry


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

    rows, reports = scan_registry(source, 2026, scan_fn=fake_scan)
    assert len(calls) == 1
    assert calls[0][0]["official_sources"] == [source[0]["url"]]
    assert len(rows) == 1
    assert reports[0]["confirmed_count"] == 1
    assert rows[0]["decision"] == "pending"
    assert rows[0]["source_origin"] == "ward_official_source_registry"


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
