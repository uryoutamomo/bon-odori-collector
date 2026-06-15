import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from export_public_events import fill_youtube_evidence_defaults, parse_youtube_evidence, write_public_js


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
