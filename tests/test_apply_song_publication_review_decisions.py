import unittest

from apply_song_publication_review_decisions import hydrate_decisions, merge_notes


class ApplySongPublicationReviewDecisionsTest(unittest.TestCase):
    def test_hydrates_compact_ledger_from_song_master(self):
        ledger = {"rows": [{"term": "東京おどり", "decision": "publish"}]}
        master = {
            "songs": [{
                "song_name": "東京おどり",
                "description": "複数会場で確認されています。",
                "youtube_urls": ["https://www.youtube.com/watch?v=sample"],
            }]
        }

        hydrated = hydrate_decisions(ledger, master)

        self.assertEqual(hydrated["rows"][0]["description"], "複数会場で確認されています。")
        self.assertEqual(hydrated["rows"][0]["decision"], "publish")

    def test_adds_publish_decisions_as_public_notes(self):
        existing = {"items": []}
        decisions = {
            "rows": [
                {
                    "term": "東京おどり",
                    "decision": "publish",
                    "description": "複数会場で確認されています。",
                    "youtube_urls": ["https://www.youtube.com/watch?v=sample"],
                },
                {"term": "除外曲", "decision": "reject", "description": "説明"},
            ]
        }

        result, summary = merge_notes(existing, decisions)

        self.assertEqual(summary["added"], 1)
        self.assertEqual(result["items"][0]["term"], "東京おどり")
        self.assertEqual(result["items"][0]["content_note_status"], "公開可")
        self.assertEqual(result["items"][0]["content_note"], "複数会場で確認されています。")
        self.assertEqual(result["items"][0]["source_urls"], ["https://www.youtube.com/watch?v=sample"])

    def test_keeps_existing_public_note(self):
        existing = {
            "items": [
                {
                    "term": "既存曲",
                    "content_note": "既存の説明",
                    "content_note_status": "公開可",
                }
            ]
        }
        decisions = {"rows": [{"term": "既存曲", "decision": "publish", "description": "新しい説明"}]}

        result, summary = merge_notes(existing, decisions)

        self.assertEqual(summary["added"], 0)
        self.assertEqual(result["items"][0]["content_note"], "既存の説明")

    def test_updates_unpublished_existing_note(self):
        existing = {
            "items": [
                {
                    "term": "要確認曲",
                    "content_note": "仮説明",
                    "content_note_status": "要確認",
                }
            ]
        }
        decisions = {"rows": [{"term": "要確認曲", "decision": "publish", "description": "公開説明"}]}

        result, summary = merge_notes(existing, decisions)

        self.assertEqual(summary["updated"], 1)
        self.assertEqual(result["items"][0]["content_note"], "公開説明")
        self.assertEqual(result["items"][0]["content_note_status"], "公開可")


if __name__ == "__main__":
    unittest.main()
