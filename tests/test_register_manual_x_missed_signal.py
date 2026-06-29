import unittest
from argparse import Namespace
from pathlib import Path
from tempfile import TemporaryDirectory

from register_manual_x_missed_signal import candidate_id, parse_x_url, register


class RegisterManualXMissedSignalTest(unittest.TestCase):
    def args(self, root):
        return Namespace(
            url="https://x.com/kagurazaka_6/status/2067528339074830638",
            summary="神楽坂エリアの重要なイベント情報として手動追加。非X根拠で裏どりする。",
            event_name="神楽坂エリアの重要イベント情報",
            venue="",
            area="神楽坂",
            date_text="",
            promotion_target="event",
            novelty="unclear",
            note="内田さん確認の見逃しURL。",
            query=["神楽坂 イベント 盆踊り 公式"],
            log=Path(root) / "data/manual_x_missed_signals.json",
            log_md=Path(root) / "data/manual_x_missed_signals.md",
            rare_out=Path(root) / "data/manual_x_rare_signal_candidates.json",
            accounts_out=Path(root) / "data/x_manual_account_candidates.json",
        )

    def test_parse_x_url(self):
        handle, tweet_id = parse_x_url("https://x.com/kagurazaka_6/status/2067528339074830638")
        self.assertEqual(handle, "kagurazaka_6")
        self.assertEqual(tweet_id, "2067528339074830638")

    def test_registers_log_rare_signal_and_account_candidate(self):
        with TemporaryDirectory() as tmp:
            args = self.args(tmp)
            result = register(args)

            self.assertEqual(result["signal"]["source_author"], "@kagurazaka_6")
            self.assertEqual(result["rare_candidate"]["candidate_id"], candidate_id(args.url))
            self.assertEqual(result["rare_candidate"]["promotion_target"], "event")
            self.assertIn("神楽坂 イベント 盆踊り 公式", result["rare_candidate"]["web_backcheck_queries"])
            self.assertEqual(result["account_candidate"]["handle"], "@kagurazaka_6")
            self.assertTrue(args.log.exists())
            self.assertTrue(args.log_md.exists())
            self.assertTrue(args.rare_out.exists())
            self.assertTrue(args.accounts_out.exists())

            register(args)
            text = args.rare_out.read_text(encoding="utf-8")
            self.assertEqual(text.count(candidate_id(args.url)), 1)


if __name__ == "__main__":
    unittest.main()
