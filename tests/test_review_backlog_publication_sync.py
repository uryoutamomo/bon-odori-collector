from scripts.apply_review_backlog_publication_sync import transform


def test_publication_sync_adds_exact_decisions_without_removing_existing_rows():
    decisions = []
    for index in range(7):
        decisions.append(
            {
                "source_id": "publication_gap",
                "source_key": f"gap:public_ready_song_missing_public:曲{index}",
                "decision": "公開同期対象",
            }
        )
    for index in range(4):
        decisions.append(
            {
                "source_id": "publication_gap",
                "source_key": f"gap:weekly_song_updated_unpublished:週次{index}",
                "decision": "公開同期対象",
            }
        )
    decisions.append(
        {
            "source_id": "publication_gap",
            "source_key": "gap:glossary_v2_missing_public:呼び名",
            "decision": "公開同期対象",
        }
    )
    site = {"items": [{"term": "既存", "category": "地域語"}], "count": 1}
    master = {
        "songs": [
            {
                "song_name": f"曲{index}",
                "public_ready": True,
                "evidence_count": index + 1,
            }
            for index in range(7)
        ]
    }
    weekly = {"updated": [{"song_name": f"週次{index}"} for index in range(4)]}
    glossary = {
        "accepted": [
            {
                "term": "呼び名",
                "decision": "採用",
                "interpretation": "公開説明",
                "confidence": "候補",
            }
        ]
    }

    result, report = transform(
        site,
        {"decisions": decisions},
        master,
        weekly,
        glossary,
        generated_at="2026-08-18T00:00:00+09:00",
    )

    assert result["count"] == 13
    assert {row["term"] for row in result["items"]} == {
        "既存",
        "呼び名",
        *(f"曲{index}" for index in range(7)),
        *(f"週次{index}" for index in range(4)),
    }
    assert report["summary"]["added_count"] == 12
    assert report["summary"]["removed_count"] == 0
