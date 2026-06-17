import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from export_public_events import (
    apply_public_recurrence_metadata,
    extract_public_source_urls,
    fill_youtube_evidence_defaults,
    parse_youtube_evidence,
    public_detail_text,
    write_public_js,
)


class ExportPublicEventsTest(unittest.TestCase):
    def test_parse_youtube_evidence_block(self):
        detail = "\n".join([
            "2025-07-19〜2025-07-21 開催予定。",
            "",
            "[youtube_evidence] 2025実績証拠",
            "- 対象イベント: 自由が丘納涼盆踊り大会",
            "- 検出日付: 2025-07-21",
            "- 動画: https://www.youtube.com/watch?v=mvHqQY2ISJE",
            "- チャンネル: 和太鼓お祭りチャンネル",
            "- サムネイル: https://i.ytimg.com/vi/mvHqQY2ISJE/maxresdefault.jpg",
            "- 曲目候補: 北海盆唄, 炭坑節, 大東京音頭",
        ])

        rows = parse_youtube_evidence(detail)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["label"], "2025実績証拠")
        self.assertEqual(rows[0]["event_name"], "自由が丘納涼盆踊り大会")
        self.assertEqual(rows[0]["detected_date"], "2025-07-21")
        self.assertEqual(rows[0]["video_url"], "https://www.youtube.com/watch?v=mvHqQY2ISJE")
        self.assertEqual(rows[0]["channel"], "和太鼓お祭りチャンネル")
        self.assertEqual(rows[0]["thumbnail_url"], "https://i.ytimg.com/vi/mvHqQY2ISJE/maxresdefault.jpg")
        self.assertEqual(rows[0]["songs"], ["北海盆唄", "炭坑節", "大東京音頭"])

    def test_ignores_block_without_video_url(self):
        self.assertEqual(parse_youtube_evidence("[youtube_evidence]\n- 曲目候補: 東京音頭"), [])

    def test_fill_youtube_evidence_defaults(self):
        rows = [{"event_name": "", "detected_date": "", "video_url": "https://www.youtube.com/watch?v=abc"}]

        filled = fill_youtube_evidence_defaults(rows, "丸の内de盆踊り", "2025-07-25")

        self.assertEqual(filled[0]["event_name"], "丸の内de盆踊り")
        self.assertEqual(filled[0]["detected_date"], "2025-07-25")

    def test_public_detail_text_hides_internal_youtube_evidence(self):
        detail = "\n".join([
            "2026-07-29〜2026-08-01 開催予定。公式発表を確認。",
            "[youtube_evidence] YouTube 2025公式URL確認済み証拠",
            "- 対象イベント: 築地本願寺納涼盆踊り大会",
            "- 公式確認URL: https://tokyofesta.com/23ku/23763/",
            "- 動画: https://www.youtube.com/watch?v=abc",
        ])

        public = public_detail_text(detail)

        self.assertIn("2026-07-29〜2026-08-01 開催予定。公式発表を確認。", public)
        self.assertNotIn("[youtube_evidence]", public)
        self.assertNotIn("YouTube", public)
        self.assertNotIn("https://", public)

    def test_extract_public_source_urls_keeps_official_urls_not_video_urls(self):
        detail = "\n".join([
            "2026発表 https://t.co/abc",
            "[youtube_evidence] YouTube 2025公式URL確認済み証拠",
            "- 公式確認URL: https://tokyofesta.com/23ku/23763/",
            "- YouTube検出元URL: https://www.nouryo-matsuri.com/pages/6314608/page_202208061239",
            "- 動画: https://www.youtube.com/watch?v=abc",
        ])

        sources = extract_public_source_urls(detail)

        self.assertEqual(
            sources,
            [
                {"label": "公式告知あり", "url": "https://www.nouryo-matsuri.com/pages/6314608/page_202208061239", "kind": "official"},
                {"label": "告知HPあり", "url": "", "kind": "web"},
                {"label": "告知投稿あり", "url": "", "kind": "post"},
            ],
        )

    def test_extract_public_source_urls_excludes_stale_official_urls(self):
        detail = "\n".join([
            "[youtube_evidence] YouTube 2025公式URL確認済み証拠",
            "- YouTube検出元URL: https://tsukijihongwanji.jp/news/10279/",
            "- 動画: https://www.youtube.com/watch?v=abc",
        ])

        self.assertEqual(extract_public_source_urls(detail), [])

    def test_extract_public_source_urls_collapses_multiple_notice_urls(self):
        detail = "\n".join([
            "発表 https://x.com/example/status/1",
            "続報 https://twitter.com/example/status/2",
            "短縮 https://t.co/abc",
        ])

        self.assertEqual(extract_public_source_urls(detail), [{"label": "告知投稿あり", "url": "", "kind": "post"}])

    def test_apply_public_recurrence_metadata_adds_production_fields(self):
        rows = apply_public_recurrence_metadata([{
            "name": "第70回 恵比寿駅前盆踊り大会",
            "venue": "JR恵比寿駅西口広場",
            "area": "渋谷区",
            "date": "2025-07-25",
            "date_end": "2025-07-26",
            "status": "開催終了",
        }])

        self.assertEqual(rows[0]["public_category"], "recurring_last_year")
        self.assertGreaterEqual(rows[0]["recurrence_score"], 0.55)
        self.assertEqual(rows[0]["edition_number"], 70)
        self.assertEqual(rows[0]["last_seen_year"], 2025)

    def test_write_public_js(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "events_public.js"

            write_public_js(path, [{"name": "自由が丘納涼盆踊り大会", "youtube_evidence": []}])

            text = path.read_text(encoding="utf-8")
            self.assertIn("const EVENTS = ", text)
            self.assertIn("自由が丘納涼盆踊り大会", text)
            self.assertTrue(text.endswith(";\n"))


if __name__ == "__main__":
    unittest.main()
