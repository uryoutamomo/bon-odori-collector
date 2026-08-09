import gzip
import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

import collect
from collection_support.x_raw_archive import RawXArchiveError, capture_raw_x_posts


class FakeS3:
    def __init__(self):
        self.objects = []

    def put_object(self, **kwargs):
        self.objects.append(kwargs)


class FailingS3:
    def __init__(self):
        self.calls = 0

    def put_object(self, **kwargs):
        self.calls += 1
        raise OSError("S3 unavailable")


class RawXArchiveTest(unittest.TestCase):
    def _tweet(self, tweet_id="123", text="盆踊り"):
        return {
            "id": tweet_id,
            "text": text,
            "createdAt": "2026-08-10T00:00:00Z",
            "author": {"userName": "bonsuke", "name": "盆助"},
            "entities": {"media": [{"media_url_https": "https://img.example/a.jpg"}]},
        }

    def test_preserves_full_text_and_deduplicates_by_tweet_id(self):
        client = FakeS3()
        full_text = "あ" * 5001
        context = {
            "route": "query", "query_id": "q-bon", "batch_id": "page-1",
            "run_id": "42", "estimated_cost_usd": 0.00015,
        }
        with patch.dict(os.environ, {"X_RAW_POSTS_S3_BUCKET": "private-test", "X_RAW_POSTS_S3_PREFIX": "private-raw"}, clear=False):
            result = capture_raw_x_posts(
                [self._tweet(text=full_text), self._tweet(text="duplicate")], context,
                client=client, captured_at="2026-08-10T01:02:03+00:00",
            )

        self.assertEqual(result["count"], 1)
        self.assertEqual(len(client.objects), 2)
        archived = json.loads(gzip.decompress(client.objects[0]["Body"]).decode("utf-8"))
        self.assertEqual(archived["tweet_id"], "123")
        self.assertEqual(archived["post_key"], "tweet:123")
        self.assertEqual(archived["text"], full_text)
        self.assertEqual(archived["media_urls"], ["https://img.example/a.jpg"])
        self.assertEqual(archived["acquisition"]["route"], "query")
        self.assertIn("captured_date=2026-08-10", result["object_key"])
        self.assertTrue(result["object_key"].startswith("private-raw/v1/"))
        self.assertEqual(client.objects[0]["ServerSideEncryption"], "AES256")
        manifest = json.loads(client.objects[1]["Body"].decode("utf-8"))
        self.assertEqual(manifest["post_keys"], ["tweet:123"])

    def test_requires_archive_bucket_and_wraps_write_failure(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RawXArchiveError, "X_RAW_POSTS_S3_BUCKET"):
                capture_raw_x_posts([self._tweet()], {}, client=FakeS3())
        failing = FailingS3()
        with patch.dict(os.environ, {"X_RAW_POSTS_S3_BUCKET": "private-test"}, clear=False):
            with patch("collection_support.x_raw_archive.time.sleep") as sleep:
                with self.assertRaisesRegex(RawXArchiveError, "after 3 attempts"):
                    capture_raw_x_posts([self._tweet()], {}, client=failing)
        self.assertEqual(failing.calls, 3)
        self.assertEqual(sleep.call_count, 2)

    def test_capture_happens_before_scoring_and_seen_advance(self):
        events = []
        tweet = self._tweet()
        config = {
            "budget": {"cost_per_tweet_usd": 0, "daily_usd": 1, "monthly_usd": 1},
            "queries": [{"id": "q-bon", "query": "盆踊り"}],
            "max_pages_per_query": 1,
            "page_sleep_sec": 0,
        }
        with (
            patch.object(collect, "TWITTERAPI_IO_KEY", "test"),
            patch.object(collect, "_load_x_config", return_value=config),
            patch.object(collect, "_x_budget_state", return_value={}),
            patch.object(collect, "_x_search", return_value={"tweets": [tweet]}),
            patch.object(collect, "capture_raw_x_posts", side_effect=lambda *_args, **_kwargs: events.append("archive")),
            patch.object(collect, "_score_voice", side_effect=lambda *_args: events.append("score") or "🟡関心"),
            patch.object(collect, "_append_x_log_row"),
        ):
            items, seen = collect.collect_x_voices(set())

        self.assertEqual(events, ["archive", "score"])
        self.assertEqual(len(items), 1)
        self.assertEqual(seen, ["https://x.com/bonsuke/status/123"])

    def test_archive_failure_propagates_without_seen_advance(self):
        config = {
            "budget": {"cost_per_tweet_usd": 0, "daily_usd": 1, "monthly_usd": 1},
            "queries": [{"id": "q-bon", "query": "盆踊り"}],
            "max_pages_per_query": 1,
        }
        with (
            patch.object(collect, "TWITTERAPI_IO_KEY", "test"),
            patch.object(collect, "_load_x_config", return_value=config),
            patch.object(collect, "_x_budget_state", return_value={}),
            patch.object(collect, "_x_search", return_value={"tweets": [self._tweet()]}),
            patch.object(collect, "capture_raw_x_posts", side_effect=RawXArchiveError("durability failed")),
        ):
            with self.assertRaisesRegex(RawXArchiveError, "durability failed"):
                collect.collect_x_voices(set())

    def test_template_has_private_bucket_retention_and_least_privilege_write(self):
        template = Path("infra/dynamodb-queue.yml").read_text(encoding="utf-8")
        for expected in (
            "RawXPostsBucket:", "RawXPostsBucketPolicy:", "BlockPublicAcls: true",
            "RestrictPublicBuckets: true", "aws:SecureTransport: \"false\"",
            "ExpirationInDays: 180", "NoncurrentDays: 30", "DaysAfterInitiation: 7",
            "PolicyName: RawXPostsArchiveAccess", "Action: s3:PutObject",
            "${RawXPostsBucket.Arn}/${RawXPostsPrefix}/*",
        ):
            self.assertIn(expected, template)


if __name__ == "__main__":
    unittest.main()
