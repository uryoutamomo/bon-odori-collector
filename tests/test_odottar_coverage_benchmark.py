import hashlib
import json
from pathlib import Path

from build_odottar_coverage_benchmark import SAFETY_BOUNDARY, build_report


ROOT = Path(__file__).resolve().parents[1]


def test_report_hashes_raw_bytes_and_never_creates_candidates() -> None:
    raw = '[{"eid":"o1","name":"A","venue":"V","area":"江戸川区","start":"2026-08-01"}]'.encode()
    report = build_report(
        raw,
        json.loads(raw),
        [{"name": "A", "venue": "V", "area": "江戸川区", "date": "2026-08-01"}],
        fetched_at="2026-08-24T00:00:00Z",
        source_url="https://odottar.com/events.json",
    )
    assert report["source"]["raw_sha256"] == hashlib.sha256(raw).hexdigest()
    assert report["canonical_write_count"] == 0
    assert report["review_inbox_candidate_count"] == 0
    assert report["safety_boundary"] == SAFETY_BOUNDARY
    assert report["summary"] == {
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
    report = build_report(raw, rows, bonsuke, fetched_at="2026-08-24T00:00:00Z", source_url="test")
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
