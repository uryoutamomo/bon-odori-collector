from scripts.apply_review_backlog_song_projection import (
    transform,
    transform_event_cards,
    transform_song_master,
)


def decision(raw, decision, target=None):
    return {
        "raw_song_name": raw,
        "decision": decision,
        "target_song_name": target,
    }


def test_bounded_projection_only_changes_reviewed_songs():
    decisions = [
        decision("ノイズ", "曲名ノイズとして除外"),
        decision("東京おんど", "既存曲へ統合", "東京音頭"),
        decision("新曲(Live)", "新規曲候補として維持", "新曲"),
    ]
    decisions.extend(
        decision(f"unused-{index}", "曲名ノイズとして除外")
        for index in range(144)
    )
    public = {
        "generated_by": "old",
        "occurrences": [
            {
                "occurrence_id": "occ_1",
                "event_name": "イベント",
                "venue": "会場",
                "year": 2025,
                "songs": [
                    {"name": "無関係", "evidence_count": 1},
                    {"name": "ノイズ", "evidence_count": 2},
                    {"name": "東京おんど", "evidence_count": 2, "evidence_urls": ["a"]},
                    {"name": "東京音頭", "evidence_count": 3, "evidence_urls": ["b"]},
                    {"name": "新曲(Live)", "evidence_count": 1},
                ],
            }
        ],
    }
    # The production guard requires every frozen title to be present. Keep the
    # unit fixture small by making the synthetic titles appear as zero-value rows.
    public["occurrences"][0]["songs"].extend(
        {"name": f"unused-{index}"} for index in range(144)
    )

    result, report = transform(
        public, {"decisions": decisions}, generated_at="2026-08-18T00:00:00+09:00"
    )

    songs = {row["name"]: row for row in result["occurrences"][0]["songs"]}
    assert set(songs) == {"無関係", "東京音頭", "新曲"}
    assert songs["東京音頭"]["evidence_count"] == 5
    assert songs["東京音頭"]["evidence_urls"] == ["a", "b"]
    assert report["summary"]["occurrence_count_before"] == 1
    assert report["summary"]["occurrence_count_after"] == 1
    assert report["summary"]["unrelated_occurrences_added"] == 0
    assert report["summary"]["unrelated_occurrences_removed"] == 0


def test_song_master_adds_aliases_and_keeps_new_candidates_non_public():
    decisions = {
        "decisions": [
            decision("東京おんど", "既存曲へ統合", "東京音頭"),
            decision("新曲(Live)", "新規曲候補として維持", "新曲"),
        ]
    }
    master = {
        "songs": [
            {
                "song_name": "東京音頭",
                "aliases": [],
                "public_ready": True,
            }
        ]
    }
    projection = {
        "occurrences": [
            {
                "occurrence_id": "occ_1",
                "event_name": "イベント",
                "venue": "会場",
                "year": 2025,
                "songs": [
                    {
                        "name": "新曲",
                        "evidence_count": 2,
                        "evidence_urls": ["https://youtu.be/example"],
                    }
                ],
            }
        ]
    }

    result, summary = transform_song_master(
        master,
        decisions,
        projection,
        generated_at="2026-08-18T00:00:00+09:00",
    )

    by_name = {row["song_name"]: row for row in result["songs"]}
    assert by_name["東京音頭"]["aliases"] == ["東京おんど"]
    assert by_name["新曲"]["public_ready"] is False
    assert by_name["新曲"]["status"] == "要確認"
    assert by_name["新曲"]["evidence_count"] == 2
    assert summary == {
        "alias_updates": 1,
        "candidate_additions": 1,
        "target_bridge_additions": 0,
        "song_count_before": 1,
        "song_count_after": 2,
    }


def test_event_cards_only_change_song_arrays():
    decisions = [
        decision("ノイズ", "曲名ノイズとして除外"),
        decision("東京おんど", "既存曲へ統合", "東京音頭"),
    ]
    decisions.extend(
        decision(f"unused-{index}", "曲名ノイズとして除外")
        for index in range(145)
    )
    events = [
        {
            "name": "イベント",
            "date": "2026-08-18",
            "venue": "会場",
            "songs": [
                {"name": "東京おんど", "probability": 80},
                {"name": "ノイズ", "probability": 90},
                {"name": "無関係", "probability": 70},
            ],
        }
    ]

    result, summary = transform_event_cards(events, {"decisions": decisions})

    assert result[0]["date"] == events[0]["date"]
    assert result[0]["venue"] == events[0]["venue"]
    assert [row["name"] for row in result[0]["songs"]] == ["東京音頭", "無関係"]
    assert summary["event_count_before"] == summary["event_count_after"] == 1
    assert summary["non_song_fields_changed"] == 0
