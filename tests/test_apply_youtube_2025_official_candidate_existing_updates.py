import unittest

from legacy.notion_writes.apply_youtube_2025_official_candidate_existing_updates import (
    has_existing_summary,
)


class ApplyYoutube2025OfficialCandidateExistingUpdatesTest(unittest.TestCase):
    def test_normal_source_url_is_not_youtube_summary_duplicate(self):
        detail = "\n".join(
            [
                "情報源: https://www.tenkamatsuri.jp/minyo/",
                "[youtube_evidence] YouTube実績証拠",
                "- 対象イベント: 山王音頭と民踊大会",
                "- 検出日付: 2026-06-13",
                "- 動画数: 16",
            ]
        )

        self.assertFalse(
            has_existing_summary(
                detail,
                "山王音頭と民踊大会",
                "https://www.tenkamatsuri.jp/minyo/",
                ["2025-06-13"],
            )
        )

    def test_detects_same_official_candidate_summary(self):
        detail = "\n".join(
            [
                "[youtube_evidence] YouTube 2025公式URL確認済み証拠",
                "- 対象イベント: 山王音頭と民踊大会",
                "- 検出日付: 2025-06-13",
                "- 動画数: 6",
                "- 公式確認URL: https://www.tenkamatsuri.jp/minyo/",
            ]
        )

        self.assertTrue(
            has_existing_summary(
                detail,
                "山王音頭と民踊大会",
                "https://www.tenkamatsuri.jp/minyo/",
                ["2025-06-13"],
            )
        )


if __name__ == "__main__":
    unittest.main()
