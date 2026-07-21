import sqlite3
import tempfile
import unittest
from pathlib import Path

from rdb_builders.build_youtube_rdb import build_youtube_rdb


class BuildYoutubeRdbTest(unittest.TestCase):
    def test_builds_normalized_sqlite_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_db = Path(tmp) / "youtube.sqlite"
            out_summary = Path(tmp) / "summary.json"

            summary = build_youtube_rdb(
                voices=[
                    {
                        "source": "youtube",
                        "account": "UC_ACTIVE",
                        "youtube_channel_id": "UC_ACTIVE",
                        "youtube_channel_title": "Active Channel",
                        "title": "山王音頭と民踊大会 2026年6月13日",
                        "text": "盆踊り\nhttps://example.com/official",
                        "media_urls": ["https://example.com/official"],
                        "url": "https://youtu.be/aaa",
                        "date": "2026-06-14T00:00:00+00:00",
                    }
                ],
                registry={
                    "channels": [
                        {
                            "channel_id": "UC_ACTIVE",
                            "channel_title": "Active Channel",
                            "status": "active",
                            "collection_enabled": True,
                            "trusted_for": ["date_evidence"],
                        }
                    ]
                },
                active_review={
                    "rows": [
                        {
                            "video_id": "aaa",
                            "video_url": "https://www.youtube.com/watch?v=aaa",
                            "title": "山王音頭と民踊大会 2026年6月13日",
                            "channel_id": "UC_ACTIVE",
                            "detected_event_date": "2026-06-13",
                            "has_bon_context": True,
                            "official_urls": ["https://example.com/official"],
                            "matched_public_event": {
                                "name": "山王音頭と民踊大会",
                                "venue": "山王パークタワー公開空地",
                                "date": "2026-06-13",
                                "score": 110,
                                "reasons": ["event_name_in_youtube"],
                            },
                            "action": "append_existing_event",
                            "priority": "high",
                        }
                    ]
                },
                setlists={
                    "occurrences": [
                        {
                            "occurrence_key": "occ1",
                            "event_name_hint": "山王音頭と民踊大会",
                            "venue": "山王パークタワー公開空地",
                            "event_date": "2026-06-13",
                            "source_video_count": 1,
                            "song_count": 1,
                            "confidence": "high",
                            "source_videos": [
                                {
                                    "url": "https://www.youtube.com/watch?v=aaa",
                                    "account": "@active",
                                    "title": "東京音頭",
                                    "published_at": "2026-06-14T00:00:00+00:00",
                                    "thumbnail_url": "https://i.ytimg.com/vi/aaa/maxresdefault.jpg",
                                }
                            ],
                            "setlist": [
                                {
                                    "number": 1,
                                    "title": "東京音頭",
                                    "url": "https://www.youtube.com/watch?v=aaa",
                                }
                            ],
                        }
                    ]
                },
                out_db=out_db,
                out_summary=out_summary,
            )

            self.assertEqual(summary["table_counts"]["channels"], 1)
            self.assertEqual(summary["table_counts"]["videos"], 1)
            self.assertEqual(summary["table_counts"]["video_event_matches"], 1)
            self.assertEqual(summary["table_counts"]["setlist_songs"], 1)

            with sqlite3.connect(out_db) as conn:
                video = conn.execute(
                    "SELECT video_url, action, detected_event_date, thumbnail_url FROM videos"
                ).fetchone()
                self.assertEqual(
                    video,
                    (
                        "https://www.youtube.com/watch?v=aaa",
                        "append_existing_event",
                        "2026-06-13",
                        "https://i.ytimg.com/vi/aaa/maxresdefault.jpg",
                    ),
                )
                official_url_count = conn.execute(
                    "SELECT COUNT(*) FROM video_official_urls"
                ).fetchone()[0]
                self.assertEqual(official_url_count, 1)


if __name__ == "__main__":
    unittest.main()
