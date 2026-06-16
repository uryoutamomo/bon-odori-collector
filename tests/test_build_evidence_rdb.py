import sqlite3
import tempfile
import unittest
from pathlib import Path

from build_evidence_rdb import build_evidence_rdb


class BuildEvidenceRdbTest(unittest.TestCase):
    def test_builds_x_posts_scores_and_candidate_reviews(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_db = Path(tmp) / "evidence.sqlite"
            out_summary = Path(tmp) / "summary.json"

            summary = build_evidence_rdb(
                voices=[
                    {
                        "source": "x_whitelist",
                        "account": "bonDbonT",
                        "name": "盆D",
                        "title": "",
                        "text": "7/20 盆踊り開催 https://example.com/event",
                        "url": "https://x.com/bonDbonT/status/12345",
                        "date": "2026-06-01T00:00:00+00:00",
                        "tags": ["⭐盆踊ラー"],
                        "media_urls": ["https://example.com/event"],
                    },
                    {
                        "source": "youtube",
                        "account": "UC_YT",
                        "youtube_channel_id": "UC_YT",
                        "youtube_channel_title": "YT Channel",
                        "title": "盆踊り動画",
                        "text": "動画説明",
                        "url": "https://youtu.be/abc123",
                        "date": "2026-06-02T00:00:00+00:00",
                    },
                ],
                x_account_scores={
                    "accounts": {
                        "bondbont": {
                            "handle": "@bonDbonT",
                            "posts_seen": 10,
                            "valuable_posts": 8,
                            "future_schedule_posts": 3,
                            "score": 9.5,
                            "status": "trusted",
                            "usefulness_rank": "S",
                            "role_tags": ["発見型"],
                        }
                    }
                },
                x_candidates={
                    "candidates": [
                        {
                            "handle": "@candidate",
                            "name": "候補",
                            "description": "盆踊り好き",
                            "candidate_score": 8.1,
                            "reasons": ["profile_keywords"],
                        }
                    ]
                },
                x_candidate_reviews={
                    "results": [
                        {
                            "handle": "@candidate",
                            "name": "候補",
                            "tweets_checked": 20,
                            "valuable_posts": 12,
                            "future_schedule_posts": 4,
                            "promote_score": 18.0,
                            "recommendation": "promote",
                            "sample_valuable_posts": [
                                {
                                    "value_score": 19,
                                    "reasons": ["future_schedule"],
                                    "text": "明日開催",
                                    "url": "https://x.com/candidate/status/999",
                                    "date": "Tue Jun 01 00:00:00 +0000 2026",
                                }
                            ],
                        }
                    ]
                },
                out_db=out_db,
                out_summary=out_summary,
            )

            self.assertEqual(summary["table_counts"]["source_posts"], 2)
            self.assertEqual(summary["table_counts"]["x_account_scores"], 1)
            self.assertEqual(summary["table_counts"]["x_candidate_accounts"], 1)
            self.assertEqual(summary["table_counts"]["x_candidate_review_sample_posts"], 1)

            with sqlite3.connect(out_db) as conn:
                x_post = conn.execute(
                    "SELECT post_key, platform, account_key FROM source_posts WHERE platform = 'x'"
                ).fetchone()
                self.assertEqual(x_post, ("x:12345", "x", "@bonDbonT"))

                youtube_post = conn.execute(
                    "SELECT post_key, platform, account_key, url FROM source_posts WHERE platform = 'youtube'"
                ).fetchone()
                self.assertEqual(
                    youtube_post,
                    ("youtube:abc123", "youtube", "UC_YT", "https://www.youtube.com/watch?v=abc123"),
                )

                external_url_count = conn.execute(
                    "SELECT COUNT(*) FROM post_urls WHERE url_kind = 'external'"
                ).fetchone()[0]
                self.assertEqual(external_url_count, 1)


if __name__ == "__main__":
    unittest.main()
