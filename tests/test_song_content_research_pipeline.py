import unittest

from apply_song_content_research_batch import content_rows, merge_notes, removal_terms
from apply_song_official_sources_batch import merge_sources, source_rows
from build_song_content_research_queue import build_queue


class SongContentResearchPipelineTest(unittest.TestCase):
    def test_build_queue_prioritizes_existing_needs_review_then_missing_high_count(self):
        song_master = {
            "songs": [
                {
                    "song_name": "整備済み",
                    "public_ready": True,
                    "good_evidence_count": 999,
                    "bon_usage_rank": "定番",
                },
                {
                    "song_name": "要確認曲",
                    "public_ready": True,
                    "good_evidence_count": 10,
                    "bon_usage_rank": "ときどき使われる",
                },
                {
                    "song_name": "未整備上位",
                    "public_ready": True,
                    "good_evidence_count": 80,
                    "bon_usage_rank": "よく使われる",
                },
            ]
        }
        notes = {
            "items": [
                {"term": "整備済み", "content_note": "公開済み", "content_note_status": "公開可"},
                {"term": "要確認曲", "content_note": "仮", "content_note_status": "要確認"},
            ]
        }

        queue = build_queue(song_master, notes, limit=10)

        self.assertEqual([row["term"] for row in queue["rows"]], ["要確認曲", "未整備上位"])
        self.assertEqual(queue["rows"][0]["priority"], "P0既存要確認")
        self.assertEqual(queue["rows"][1]["priority"], "P1未整備50件以上")

    def test_content_rows_only_accepts_public_ready_reviewed_notes(self):
        batch = {
            "rows": [
                {"term": "採用曲", "content_note": "説明", "content_note_status": "公開可"},
                {"term": "保留曲", "content_note": "説明", "content_note_status": "要確認"},
                {"term": "空説明", "content_note": "", "content_note_status": "公開可"},
                {
                    "term": "旧別名",
                    "content_note": "説明",
                    "content_note_status": "公開可",
                    "application_status": "superseded_by_canonical_term",
                },
            ]
        }

        self.assertEqual(content_rows(batch), [{
            "term": "採用曲",
            "content_note": "説明",
            "content_note_status": "公開可",
            "source_urls": [],
            "research_memo": "",
        }])

    def test_merge_notes_updates_existing_and_appends_new_terms(self):
        existing = {
            "generated_by": "test",
            "items": [
                {"term": "既存曲", "content_note": "古い", "content_note_status": "要確認"},
            ],
        }
        rows = [
            {
                "term": "既存曲",
                "content_note": "新しい説明",
                "content_note_status": "公開可",
                "source_urls": ["https://example.com/a"],
                "research_memo": "確認済み",
            },
            {
                "term": "新規曲",
                "content_note": "新規説明",
                "content_note_status": "公開可",
                "source_urls": [],
                "research_memo": "",
            },
        ]

        merged, applied, removed = merge_notes(existing, rows)

        self.assertEqual(applied, ["既存曲", "新規曲"])
        self.assertEqual(removed, [])
        self.assertEqual([item["term"] for item in merged["items"]], ["既存曲", "新規曲"])
        self.assertEqual(merged["items"][0]["content_note"], "新しい説明")
        self.assertEqual(merged["items"][0]["source_urls"], ["https://example.com/a"])

    def test_merge_notes_can_remove_superseded_legacy_term(self):
        existing = {
            "items": [
                {"term": "旧別名", "content_note": "古い説明", "content_note_status": "要確認"},
                {"term": "正規名", "content_note": "説明", "content_note_status": "公開可"},
            ]
        }
        batch = {"remove_terms": ["旧別名", "", 123]}

        merged, applied, removed = merge_notes(existing, [], removal_terms(batch))

        self.assertEqual(applied, [])
        self.assertEqual(removed, ["旧別名"])
        self.assertEqual([item["term"] for item in merged["items"]], ["正規名"])

    def test_merge_official_sources_keeps_note_and_prepends_official_urls(self):
        existing = {
            "items": [
                {
                    "term": "既存曲",
                    "content_note": "説明",
                    "content_note_status": "公開可",
                    "source_urls": ["https://ja.wikipedia.org/wiki/example"],
                },
            ],
        }
        batch = {
            "rows": [
                {
                    "term": "既存曲",
                    "official_source_urls": ["https://official.example/song"],
                    "official_source_memo": "公式ページで発売情報を確認。",
                },
                {
                    "term": "未登録曲",
                    "official_source_urls": ["https://official.example/missing"],
                },
            ]
        }

        merged, applied, skipped = merge_sources(existing, source_rows(batch))

        self.assertEqual(applied, ["既存曲"])
        self.assertEqual(skipped, [{"term": "未登録曲", "reason": "missing_existing_content_note"}])
        self.assertEqual(merged["items"][0]["content_note"], "説明")
        self.assertEqual(merged["items"][0]["source_urls"], [
            "https://official.example/song",
            "https://ja.wikipedia.org/wiki/example",
        ])
        self.assertEqual(merged["items"][0]["official_source_urls"], ["https://official.example/song"])
        self.assertEqual(merged["items"][0]["official_source_memos"], ["公式ページで発売情報を確認。"])


if __name__ == "__main__":
    unittest.main()
