import json
import tempfile
import unittest
from pathlib import Path

from build_song_publication_review import build_candidates, read_decisions


class BuildSongPublicationReviewTest(unittest.TestCase):
    def test_build_candidates_skips_broken_alias_when_canonical_has_note(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            glossary = tmp_path / "glossary.json"
            youtube_master = tmp_path / "youtube_song_master.json"
            glossary.write_text(
                json.dumps(
                    {
                        "items": [
                            {"term": "000年音頭", "category_label": "曲名・踊り名"},
                            {
                                "term": "2000年音頭",
                                "category_label": "曲名・踊り名",
                                "content_note": "公開済み",
                            },
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            youtube_master.write_text(
                json.dumps(
                    {
                        "songs": [
                            {
                                "song_name": "2000年音頭",
                                "good_evidence_count": 48,
                                "bon_usage_score": 95,
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            candidates = build_candidates(glossary, youtube_master)

        self.assertEqual(candidates, [])

    def test_build_candidates_canonicalizes_broken_2000_ondo_label(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            glossary = tmp_path / "glossary.json"
            youtube_master = tmp_path / "youtube_song_master.json"
            glossary.write_text(
                json.dumps({"items": [{"term": "000年音頭", "category_label": "曲名・踊り名"}]}, ensure_ascii=False),
                encoding="utf-8",
            )
            youtube_master.write_text(
                json.dumps(
                    {
                        "songs": [
                            {
                                "song_name": "2000年音頭",
                                "good_evidence_count": 48,
                                "bon_usage_score": 95,
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            candidates = build_candidates(glossary, youtube_master)

        self.assertEqual([row["term"] for row in candidates], ["2000年音頭"])

    def test_read_decisions_accepts_export_envelope(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "decisions.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "rows": [
                            {"term": "東京おどり", "decision": "publish", "note": "掲載OK"},
                            {"term": "未判断曲", "decision": "", "note": ""},
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            decisions, source = read_decisions(path)

        self.assertEqual(source, str(path))
        self.assertEqual(decisions, {"東京おどり": {"decision": "publish", "note": "掲載OK"}})

    def test_read_decisions_accepts_legacy_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "decisions.json"
            path.write_text(
                json.dumps([{"term": "すみだ音頭", "decision": "research", "note": ""}], ensure_ascii=False),
                encoding="utf-8",
            )

            decisions, _ = read_decisions(path)

        self.assertEqual(decisions, {"すみだ音頭": {"decision": "research", "note": ""}})


if __name__ == "__main__":
    unittest.main()
