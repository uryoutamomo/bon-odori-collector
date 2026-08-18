#!/usr/bin/env python3
"""Apply the 12 frozen publication-sync decisions to a site glossary JSON."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DEFAULT_DECISIONS = DATA / "review_backlog_decision_overlay.json"
DEFAULT_SONG_MASTER = DATA / "youtube_song_master.json"
DEFAULT_WEEKLY = DATA / "weekly_song_review_apply_result.json"
DEFAULT_GLOSSARY_REVIEW = DATA / "glossary_v2_oto123_review_result.json"
DEFAULT_OUT = DATA / "review_backlog_site_glossary_preview.json"
DEFAULT_REPORT = DATA / "review_backlog_publication_sync_report.json"
CONFIRM_PHRASE = "APPLY REVIEW BACKLOG PUBLICATION SYNC"

CATEGORY_ORDER = {
    "行動語": 0,
    "団体語": 1,
    "地域語": 2,
    "会場別名": 3,
    "イベント別名": 4,
    "曲名": 5,
}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def song_item(name: str, source: dict, *, confidence: str) -> dict:
    return {
        "term": name,
        "reading": "",
        "description": source.get("description")
        or "盆踊り会場の曲目として確認されている曲です。",
        "tags": ["曲名・踊り名"],
        "category": "曲名",
        "category_label": "曲名・踊り名",
        "roles": [],
        "status": "有効",
        "confidence": confidence,
        "source_count": source.get("good_evidence_count")
        or source.get("evidence_count")
        or 1,
        "youtube_urls": source.get("youtube_urls") or [],
        "aliases": source.get("aliases") or [],
        "bon_usage_rank": source.get("bon_usage_rank") or "",
        "bon_usage_score": source.get("bon_usage_score") or 0,
        "song_genre": source.get("song_genre") or "",
        "song_genre_key": source.get("song_genre_key") or "",
        "genre_confidence": source.get("genre_confidence") or "",
        "genre_basis": source.get("genre_basis") or "",
        "genre_review_status": source.get("genre_review_status") or "",
    }


def transform(
    site_glossary: dict,
    decision_overlay: dict,
    song_master: dict,
    weekly: dict,
    glossary_review: dict,
    *,
    generated_at: str,
):
    decisions = [
        row
        for row in decision_overlay.get("decisions") or []
        if row.get("source_id") == "publication_gap"
        and row.get("decision") == "公開同期対象"
    ]
    if len(decisions) != 12:
        raise ValueError(f"expected 12 publication sync decisions, got {len(decisions)}")

    master_by_name = {
        row["song_name"]: row for row in song_master.get("songs") or []
    }
    weekly_by_name = {
        row["song_name"]: row for row in weekly.get("updated") or []
    }
    glossary_by_term = {
        row["term"]: row for row in glossary_review.get("accepted") or []
    }
    items = [dict(row) for row in site_glossary.get("items") or []]
    existing = {row.get("term") for row in items}
    added = []

    for decision in decisions:
        gap = decision["source_key"].removeprefix("gap:")
        kind, term = gap.split(":", 1)
        if term in existing:
            continue
        if kind == "public_ready_song_missing_public":
            source = master_by_name.get(term)
            if not source or source.get("public_ready") is not True:
                raise ValueError(f"public-ready song source missing: {term}")
            item = song_item(term, source, confidence=source.get("status") or "曲DB")
        elif kind == "weekly_song_updated_unpublished":
            source = weekly_by_name.get(term)
            if not source:
                raise ValueError(f"weekly reviewed song source missing: {term}")
            item = song_item(
                term,
                {
                    "description": "週次曲レビューで採用された盆踊り曲です。",
                    "evidence_count": 1,
                },
                confidence="週次採用",
            )
        elif kind == "glossary_v2_missing_public":
            source = glossary_by_term.get(term)
            if not source or source.get("decision") != "採用":
                raise ValueError(f"accepted glossary source missing: {term}")
            item = {
                "term": term,
                "reading": "",
                "description": source.get("interpretation") or source.get("reason") or term,
                "tags": ["呼び名・略語"],
                "category": "団体語",
                "category_label": "呼び名・略語",
                "roles": [],
                "status": "候補",
                "confidence": source.get("confidence") or "候補",
                "source_count": 1,
            }
        else:
            raise ValueError(f"unsupported publication sync gap: {gap}")
        items.append(item)
        existing.add(term)
        added.append(term)

    if len(added) != 12:
        raise ValueError(
            f"expected to add 12 absent publication terms, added {len(added)}; already present or stale decision"
        )
    items.sort(
        key=lambda row: (
            CATEGORY_ORDER.get(row.get("category"), 99),
            row.get("reading") or row.get("term") or "",
            row.get("term") or "",
        )
    )
    result = dict(site_glossary)
    result["generated_by"] = "scripts/apply_review_backlog_publication_sync.py"
    result["generated_at"] = generated_at
    result["items"] = items
    result["count"] = len(items)
    result["review_backlog_publication_sync"] = {
        "applied_at": generated_at,
        "decision_count": 12,
        "added_terms": added,
    }
    report = {
        "generated_by": "scripts/apply_review_backlog_publication_sync.py",
        "generated_at": generated_at,
        "summary": {
            "decision_count": 12,
            "site_term_count_before": len(site_glossary.get("items") or []),
            "site_term_count_after": len(items),
            "added_count": len(added),
            "removed_count": 0,
            "added_terms": added,
        },
    }
    return result, report


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site-glossary", type=Path, required=True)
    parser.add_argument("--decisions", type=Path, default=DEFAULT_DECISIONS)
    parser.add_argument("--song-master", type=Path, default=DEFAULT_SONG_MASTER)
    parser.add_argument("--weekly", type=Path, default=DEFAULT_WEEKLY)
    parser.add_argument("--glossary-review", type=Path, default=DEFAULT_GLOSSARY_REVIEW)
    parser.add_argument("--generated-at", required=True)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    if args.apply and args.confirm != CONFIRM_PHRASE:
        parser.error(f"--apply requires --confirm '{CONFIRM_PHRASE}'")

    result, report = transform(
        load(args.site_glossary),
        load(args.decisions),
        load(args.song_master),
        load(args.weekly),
        load(args.glossary_review),
        generated_at=args.generated_at,
    )
    if args.apply:
        backup = args.site_glossary.with_suffix(
            args.site_glossary.suffix + ".pre-llm-review.bak"
        )
        shutil.copy2(args.site_glossary, backup)
        write_json(args.site_glossary, result)
        report["mode"] = "apply"
        report["site_glossary_written"] = str(args.site_glossary)
        report["backup"] = str(backup)
    else:
        write_json(args.out, result)
        report["mode"] = "dry_run"
        report["preview"] = str(args.out)
    write_json(args.report, report)
    print(json.dumps(report["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
