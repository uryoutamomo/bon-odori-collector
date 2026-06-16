"""Rebuild all local SQLite RDB snapshots in dependency order."""

from build_bon_odori_rdb import build_bon_odori_rdb
from build_evidence_rdb import build_evidence_rdb, load_json as load_evidence_json
from build_notion_rdb import build_notion_rdb
from build_youtube_rdb import build_youtube_rdb, load_json as load_youtube_json
from build_evidence_rdb import VOICES, X_ACCOUNT_SCORES, X_CANDIDATES, X_CANDIDATE_REVIEWS
from build_youtube_rdb import REGISTRY, ACTIVE_REVIEW, SETLIST_OCCURRENCES
from export_rdb_review_report import build_report, write_report
from export_rdb_apply_plans import build_plans, write_plans


def main():
    notion = build_notion_rdb()
    evidence = build_evidence_rdb(
        load_evidence_json(VOICES, []),
        load_evidence_json(X_ACCOUNT_SCORES, {"accounts": {}}),
        load_evidence_json(X_CANDIDATES, {"candidates": []}),
        load_evidence_json(X_CANDIDATE_REVIEWS, {"results": []}),
    )
    youtube = build_youtube_rdb(
        load_youtube_json(VOICES, []),
        load_youtube_json(REGISTRY, {"channels": []}),
        load_youtube_json(ACTIVE_REVIEW, {"rows": []}),
        load_youtube_json(SETLIST_OCCURRENCES, {"occurrences": []}),
    )
    unified = build_bon_odori_rdb()
    report = build_report()
    write_report(report)
    event_plan, song_source, apply_summary = build_plans()
    write_plans(event_plan, song_source, apply_summary)
    print("RDB snapshots rebuilt")
    print(f"  notion: {notion['table_counts']}")
    print(f"  evidence: {evidence['table_counts']}")
    print(f"  youtube: {youtube['table_counts']}")
    print(f"  bon_odori: {unified['table_counts']}")
    print(
        "  review_report: "
        f"matched_existing_event={len(report['matched_existing_event'])}, "
        f"needs_confirmation_or_hold={len(report['needs_confirmation_or_hold'])}, "
        f"unmatched_songs_top={len(report['unmatched_songs_top'])}"
    )
    print(
        "  apply_plans: "
        f"event_plan={apply_summary['event_plan_counts']}, "
        f"song_review_candidates={apply_summary['song_review_candidates']}"
    )


if __name__ == "__main__":
    main()
