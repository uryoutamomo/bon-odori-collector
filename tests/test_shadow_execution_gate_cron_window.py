"""Cron window ガードが日次cron自身を止めないことを守るテスト。

2026-07-21〜25、collect.yml の scheduled 実行が5日連続で
"scheduled YouTube aggregate dual-write execution is forbidden during
17:20-18:00 JST" で失敗した。cron 定義は 15:13 JST だが、GitHub の
スケジュール遅延で毎日 17:22〜17:43 JST に起動し、cron を守るための
ガードに cron 自身が弾かれていた。
"""

import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from review_inbox_adapters.shadow_execution_gate import (
    CRON_SERIALIZED_ENV,
    require_outside_cron_window,
)
from review_inbox_adapters.source_writer import SourceWriterError


ROOT = Path(__file__).resolve().parents[1]
JST = ZoneInfo("Asia/Tokyo")
LABEL = "scheduled YouTube aggregate dual-write"
# 実際に失敗した5日分の起動時刻(JST)
OBSERVED_DELAYED_STARTS = ("17:22", "17:40", "17:43")


def _at(hhmm):
    hour, minute = (int(part) for part in hhmm.split(":"))
    return datetime(2026, 7, 25, hour, minute, tzinfo=JST)


class CronWindowGateTest(unittest.TestCase):
    def test_blocks_ad_hoc_run_inside_window(self):
        for hhmm in OBSERVED_DELAYED_STARTS:
            with self.subTest(hhmm=hhmm):
                with self.assertRaises(SourceWriterError):
                    require_outside_cron_window(_at(hhmm), run_label=LABEL, environ={})

    def test_allows_cron_serialized_run_inside_window(self):
        for hhmm in OBSERVED_DELAYED_STARTS:
            with self.subTest(hhmm=hhmm):
                require_outside_cron_window(
                    _at(hhmm), run_label=LABEL, environ={CRON_SERIALIZED_ENV: "true"}
                )

    def test_allows_any_run_outside_window(self):
        for hhmm in ("15:13", "17:19", "18:00", "18:01"):
            with self.subTest(hhmm=hhmm):
                require_outside_cron_window(_at(hhmm), run_label=LABEL, environ={})

    def test_falsey_flag_does_not_open_the_gate(self):
        for value in ("", "false", "0", "no", "off"):
            with self.subTest(value=value):
                with self.assertRaises(SourceWriterError):
                    require_outside_cron_window(
                        _at("17:43"), run_label=LABEL, environ={CRON_SERIALIZED_ENV: value}
                    )


class CollectWorkflowDeclaresCronSerializedRunTest(unittest.TestCase):
    def test_every_scheduled_dual_write_step_sets_the_flag(self):
        workflow = yaml.safe_load(
            (ROOT / ".github" / "workflows" / "collect.yml").read_text(encoding="utf-8")
        )
        steps = workflow["jobs"]["build"]["steps"]
        scheduled_steps = [
            step
            for step in steps
            if "_scheduled.py" in str(step.get("run") or "")
        ]

        self.assertTrue(scheduled_steps, "collect.yml に scheduled dual-write ステップがない")
        for step in scheduled_steps:
            with self.subTest(step=step.get("name")):
                self.assertEqual(
                    str((step.get("env") or {}).get(CRON_SERIALIZED_ENV, "")).lower(),
                    "true",
                )


if __name__ == "__main__":
    unittest.main()
