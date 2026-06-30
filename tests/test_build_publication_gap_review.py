import json

import build_publication_gap_review as mod


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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

    payload = mod.build_rows()

    assert payload["generated_by"] == "build_publication_gap_review.py"
    assert payload["summary"]["accepted_glossary_v2_missing_public"] == 1
    assert payload["summary"]["weekly_applied_terms_missing_public"] == 1
    assert payload["summary"]["public_ready_songs_missing_public"] == 1
    assert payload["summary"]["weekly_updated_songs_missing_public"] == 1
    assert payload["summary"]["public_occurrence_songs_not_in_master"] == 1

    gap_ids = {row["gap_id"] for row in payload["rows"]}
    assert "glossary_v2_missing_public:採用用語" in gap_ids
    assert "weekly_term_missing_public:週次用語" in gap_ids
    assert "public_ready_song_missing_public:公開可曲" in gap_ids
    assert "weekly_song_updated_unpublished:週次曲" in gap_ids
    assert "public_occurrence_song_not_in_master:未登録曲" in gap_ids
