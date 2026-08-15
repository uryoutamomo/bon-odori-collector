"""検索クエリの読み取り位置（since_time watermark）の検査。

従来の検索は毎回1ページ目から読み直し、既読URLは保存時に捨てていたが課金は発生していた。
2026-08-11の実測では1,760件取得のうち新規は660件で、残り1,100件が既読の読み直しである。
ここで守りたいのは「安くなったが取れなくなった」を起こさないことなので、
費用が下がる仕組みそのものより、**窓を進めてよい条件**を厚く検査する。
"""

import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

import collect


def payment_required():
    return urllib.error.HTTPError(
        "https://api.twitterapi.io/test",
        402,
        "Payment Required",
        {},
        None,
    )


def tweet(tweet_id, text="盆踊りに行った"):
    return {"id": str(tweet_id), "text": text, "author": {"userName": "tester"}}


def full_page(start, count=20):
    return [tweet(start + i) for i in range(count)]


class XSearchWatermarkTest(unittest.TestCase):
    def config(self, *, max_pages=8, watermark=None, queries=None):
        cfg = {
            "budget": {"cost_per_tweet_usd": 0.00015, "daily_usd": 10, "monthly_usd": 100},
            "queries": queries or [{"id": "q-base", "query": "盆踊り lang:ja"}],
            "max_pages_per_query": max_pages,
            "page_sleep_sec": 0,
        }
        if watermark is not None:
            cfg["search_watermark"] = watermark
        return cfg

    def run_collection(self, tmp, cfg, search, *, existing_marks=None, seen=None):
        """collect_x_voices を tmp ディレクトリ内だけで走らせる。"""
        budget_path = Path(tmp) / "x_budget.json"
        watermark_path = Path(tmp) / "x_query_watermarks.json"
        if existing_marks is not None:
            watermark_path.write_text(
                json.dumps({"schema_version": 1, "queries": existing_marks}),
                encoding="utf-8",
            )
        with (
            patch.object(collect, "TWITTERAPI_IO_KEY", "test"),
            patch.object(collect, "X_BUDGET_FILE", str(budget_path)),
            patch.object(collect, "_load_x_config", return_value=cfg),
            patch.object(collect, "_x_budget_state", return_value={}),
            patch.object(collect, "_x_search", side_effect=search) as searched,
            patch.object(collect, "capture_raw_x_posts"),
            patch.object(collect, "_append_x_log_row"),
        ):
            items, _ = collect.collect_x_voices(set(seen or []))
        marks = {}
        if watermark_path.exists():
            marks = json.loads(watermark_path.read_text(encoding="utf-8"))["queries"]
        return items, marks, searched

    def test_first_run_reads_from_the_initial_lookback_window(self):
        """記録が無いときだけ、設定した日数分さかのぼる。"""
        cfg = self.config(watermark={"enabled": True, "initial_lookback_days": 3})
        with tempfile.TemporaryDirectory() as tmp:
            _, _, searched = self.run_collection(tmp, cfg, [{"tweets": []}])

        sent_query = searched.call_args.args[0]
        self.assertIn("since_time:", sent_query)
        since = int(sent_query.split("since_time:")[1].split()[0])
        now = collect.datetime.now(collect.timezone.utc).timestamp()
        self.assertAlmostEqual(now - since, 3 * 86400, delta=120)

    def test_recorded_watermark_is_used_instead_of_the_lookback(self):
        cfg = self.config(watermark={"enabled": True, "initial_lookback_days": 3})
        with tempfile.TemporaryDirectory() as tmp:
            _, _, searched = self.run_collection(
                tmp,
                cfg,
                [{"tweets": []}],
                existing_marks={"q-base": {"since_time": 1723000000}},
            )

        self.assertIn("since_time:1723000000", searched.call_args.args[0])

    def test_completed_query_advances_the_watermark_with_an_overlap(self):
        """読み切れたクエリだけ窓を進める。重なりを残すのは境界の取りこぼし防止。"""
        cfg = self.config(watermark={"enabled": True, "overlap_minutes": 60})
        started = collect.datetime.now(collect.timezone.utc).timestamp()
        with tempfile.TemporaryDirectory() as tmp:
            _, marks, _ = self.run_collection(tmp, cfg, [{"tweets": []}])

        self.assertIn("q-base", marks)
        self.assertAlmostEqual(marks["q-base"]["since_time"], started - 3600, delta=120)

    def test_page_limited_query_does_not_advance_the_watermark(self):
        """ページ上限で切れたら窓を進めない（進めると未読の時間帯が恒久的に消える）。"""
        pages = [
            {"tweets": full_page(1), "has_next_page": True, "next_cursor": "c1"},
            {"tweets": full_page(21), "has_next_page": True, "next_cursor": "c2"},
        ]
        cfg = self.config(max_pages=2, watermark={"enabled": True})
        with tempfile.TemporaryDirectory() as tmp:
            items, marks, searched = self.run_collection(
                tmp,
                cfg,
                pages,
                existing_marks={"q-base": {"since_time": 1723000000}},
            )

        self.assertEqual(len(items), 40)
        self.assertEqual(searched.call_count, 2)
        # 読み切れていないので据え置き。次回も同じ地点から読み直せる。
        self.assertEqual(marks["q-base"]["since_time"], 1723000000)

    def test_http_failure_does_not_advance_the_watermark(self):
        """課金切れ（402）で落ちた時間帯を、読んだことにしない。"""
        cfg = self.config(watermark={"enabled": True})
        with tempfile.TemporaryDirectory() as tmp:
            _, marks, _ = self.run_collection(
                tmp,
                cfg,
                payment_required(),
                existing_marks={"q-base": {"since_time": 1723000000}},
            )

        self.assertEqual(marks["q-base"]["since_time"], 1723000000)

    def test_zero_new_page_stops_paging_but_still_completes(self):
        """新規0件のページに達したら既読領域なので打ち切る。窓は進めてよい。"""
        pages = [
            {"tweets": full_page(1), "has_next_page": True, "next_cursor": "c1"},
            {"tweets": full_page(1), "has_next_page": True, "next_cursor": "c2"},
            {"tweets": full_page(41), "has_next_page": True, "next_cursor": "c3"},
        ]
        cfg = self.config(max_pages=8, watermark={"enabled": True, "overlap_minutes": 0})
        with tempfile.TemporaryDirectory() as tmp:
            items, marks, searched = self.run_collection(tmp, cfg, pages)

        # 2ページ目はすべて1ページ目と同じ投稿＝新規0件なので、3ページ目は取りに行かない。
        self.assertEqual(searched.call_count, 2)
        self.assertEqual(len(items), 20)
        self.assertIn("q-base", marks)

    def test_zero_new_page_stop_can_be_disabled(self):
        pages = [
            {"tweets": full_page(1), "has_next_page": True, "next_cursor": "c1"},
            {"tweets": full_page(1), "has_next_page": True, "next_cursor": "c2"},
            {"tweets": full_page(41), "has_next_page": False},
        ]
        cfg = self.config(
            max_pages=8,
            watermark={"enabled": True, "stop_after_zero_new_page": False},
        )
        with tempfile.TemporaryDirectory() as tmp:
            items, _, searched = self.run_collection(tmp, cfg, pages)

        self.assertEqual(searched.call_count, 3)
        self.assertEqual(len(items), 40)

    def test_disabled_watermark_keeps_the_previous_behaviour(self):
        """緊急時に設定だけで元の全件読み直しへ戻せること。"""
        cfg = self.config(watermark={"enabled": False})
        with tempfile.TemporaryDirectory() as tmp:
            _, marks, searched = self.run_collection(tmp, cfg, [{"tweets": []}])

        self.assertEqual(searched.call_args.args[0], "盆踊り lang:ja")
        self.assertEqual(marks, {})

    def test_explicit_since_time_in_the_query_is_left_alone(self):
        cfg = self.config(
            watermark={"enabled": True},
            queries=[{"id": "q-fixed", "query": "盆踊り since_time:1700000000"}],
        )
        with tempfile.TemporaryDirectory() as tmp:
            _, _, searched = self.run_collection(tmp, cfg, [{"tweets": []}])

        self.assertEqual(searched.call_args.args[0], "盆踊り since_time:1700000000")

    def test_per_query_page_limit_overrides_the_default(self):
        pages = [
            {"tweets": full_page(1), "has_next_page": True, "next_cursor": "c1"},
            {"tweets": full_page(21), "has_next_page": True, "next_cursor": "c2"},
            {"tweets": full_page(41), "has_next_page": True, "next_cursor": "c3"},
        ]
        cfg = self.config(
            max_pages=8,
            watermark={"enabled": True},
            queries=[{"id": "q-base", "query": "盆踊り", "max_pages": 2}],
        )
        with tempfile.TemporaryDirectory() as tmp:
            _, _, searched = self.run_collection(tmp, cfg, pages)

        self.assertEqual(searched.call_count, 2)

    def test_broken_watermark_file_falls_back_to_the_lookback(self):
        """状態ファイルが壊れても収集を止めない。"""
        cfg = self.config(watermark={"enabled": True, "initial_lookback_days": 1})
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "x_query_watermarks.json").write_text("{ broken", encoding="utf-8")
            _, _, searched = self.run_collection(tmp, cfg, [{"tweets": []}])

        sent_query = searched.call_args.args[0]
        since = int(sent_query.split("since_time:")[1].split()[0])
        now = collect.datetime.now(collect.timezone.utc).timestamp()
        self.assertAlmostEqual(now - since, 86400, delta=120)

    def test_other_queries_keep_their_own_position(self):
        """1本が失敗しても、他のクエリの位置は巻き戻らない。"""
        cfg = self.config(
            max_pages=1,
            watermark={"enabled": True, "overlap_minutes": 0},
            queries=[
                {"id": "q-a", "query": "盆踊りA"},
                {"id": "q-b", "query": "盆踊りB"},
            ],
        )
        with tempfile.TemporaryDirectory() as tmp:
            _, marks, _ = self.run_collection(
                tmp,
                cfg,
                [payment_required(), {"tweets": []}],
                existing_marks={"q-a": {"since_time": 1723000000}},
            )

        self.assertEqual(marks["q-a"]["since_time"], 1723000000)
        self.assertGreater(marks["q-b"]["since_time"], 1723000000)


class XSearchWatermarkPersistenceTest(unittest.TestCase):
    def test_workflow_commits_the_watermark_and_the_cost_ledger(self):
        """状態が残らないと毎回初回扱いになり、既読分の課金が戻る。"""
        workflow = (
            Path(__file__).resolve().parents[1] / ".github" / "workflows" / "collect.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("git add data/x_query_watermarks.json", workflow)
        self.assertIn("git add data/x_cost_ledger.json", workflow)


if __name__ == "__main__":
    unittest.main()
