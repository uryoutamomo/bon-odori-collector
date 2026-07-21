import json
import sqlite3

from public_export_support import build_publication_gap_review as mod


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def create_master_db(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE event_series (
              series_id TEXT PRIMARY KEY,
              canonical_name TEXT NOT NULL,
              source_url TEXT
            );
            CREATE TABLE event_occurrences (
              occurrence_id TEXT PRIMARY KEY,
              origin TEXT NOT NULL,
              series_id TEXT NOT NULL,
              event_year INTEGER NOT NULL,
              display_name TEXT NOT NULL,
              venue_id TEXT,
              date_start TEXT,
              date_end TEXT,
              date_status TEXT,
              lifecycle_status TEXT,
              confidence TEXT,
              source_kind TEXT,
              source_url TEXT,
              detail TEXT
            );
            CREATE TABLE venues (
              venue_id TEXT PRIMARY KEY,
              canonical_name TEXT,
              area TEXT,
              review_status TEXT
            );
            """
        )
        conn.execute(
            "INSERT INTO event_series VALUES (?, ?, ?)",
            ("ser_1", "鉄砲洲児童公園 盆踊り", "https://x.com/iri2choukai/status/2069959259895496872"),
        )
        conn.execute(
            """
            INSERT INTO event_occurrences VALUES (
              ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                "occ_1",
                "curated",
                "ser_1",
                2026,
                "鉄砲洲児童公園 盆踊り",
                None,
                None,
                None,
                "unknown",
                "未確認",
                "unknown",
                "notion_events",
                "https://x.com/iri2choukai/status/2069959259895496872",
                "",
            ),
        )


def test_build_rows_classifies_publication_gaps(tmp_path, monkeypatch):
    repo_root = tmp_path / "collector"
    site_root = tmp_path / "site"
    monkeypatch.setattr(mod, "ROOT", repo_root)
    monkeypatch.setattr(mod, "SITE_ROOT", site_root)

    write_json(repo_root / "data" / "glossary_v2_oto123_review_result.json", {"accepted": [{"term": "採用用語"}]})
    write_json(repo_root / "data" / "weekly_harvest_human13_apply_result.json", {"applied_terms": [{"term": "週次用語"}]})
    write_json(repo_root / "data" / "weekly_song_review_apply_result.json", {"updated": [{"song_name": "週次曲"}]})
    write_json(
        repo_root / "data" / "youtube_song_master.json",
        {
            "songs": [
                {"song_name": "公開可曲", "public_ready": True},
                {
                    "song_name": "週次曲",
                    "public_ready": False,
                    "review_reason": "needs review",
                    "status": "review",
                    "evidence_count": 2,
                },
            ]
        },
    )
    write_json(
        repo_root / "data" / "public" / "event_song_occurrences_public.json",
        {"occurrences": [{"songs": [{"name": "公開可曲"}, {"name": "未登録曲"}]}]},
    )
    write_json(site_root / "data" / "glossary_public.json", {"items": [{"term": "既存用語", "category": "用語"}]})
    write_json(site_root / "data" / "song_priors.json", {"songs": {"公開可曲": {}}})
    write_json(site_root / "data" / "events_public.json", [])
    monkeypatch.setattr(mod, "MASTER_DB_PATH", repo_root / "data" / "bon_odori_master.sqlite")
    create_master_db(mod.MASTER_DB_PATH)

    payload = mod.build_rows()

    assert payload["generated_by"] == "build_publication_gap_review.py"
    assert payload["summary"]["accepted_glossary_v2_missing_public"] == 1
    assert payload["summary"]["weekly_applied_terms_missing_public"] == 1
    assert payload["summary"]["public_ready_songs_missing_public"] == 1
    assert payload["summary"]["weekly_updated_songs_missing_public"] == 1
    assert payload["summary"]["public_occurrence_songs_not_in_master"] == 1
    assert payload["summary"]["event_publication_blocked_count"] == 1
    assert payload["summary"]["event_publication_blocked_by_reason"] == {
        "missing_venue_id": 1,
        "missing_date_start": 1,
    }

    gap_ids = {row["gap_id"] for row in payload["rows"]}
    assert "glossary_v2_missing_public:採用用語" in gap_ids
    assert "weekly_term_missing_public:週次用語" in gap_ids
    assert "public_ready_song_missing_public:公開可曲" in gap_ids
    assert "weekly_song_updated_unpublished:週次曲" in gap_ids
    assert "public_occurrence_song_not_in_master:未登録曲" in gap_ids
    assert "event_publication_blocked:occ_1" in gap_ids

    event_row = next(row for row in payload["rows"] if row["gap_id"] == "event_publication_blocked:occ_1")
    assert event_row["domain"] == "イベント"
    assert event_row["priority_label"] == "P0"
    assert event_row["recommended_action"] == "review_and_apply_event_occurrence_to_master_rdb"
