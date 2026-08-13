"""公開JSONの不変条件 INV-PJS-003 を守るテスト。

`docs/spec/L2/public-json.md` を参照。守っているのは次の1つ。

- INV-PJS-003: 59フィールドは全イベントの和集合であり、個々のイベントには欠けるものがある。
  読む側は、フィールドが欠けている前提で書く。

**「欠けていること自体が情報」**というのがこの不変条件の要点である。
確定した日付があるイベントには予測が付かず、予測もできないイベントには季節ヒントだけが付く。
collector 側が「どのイベントにも全フィールドを必ず埋める」ようにすると、
その瞬間に確定と推測の区別が公開JSONから失われる。

そこで2方向から検査する。

1. 生成の入口（`build_public_events_from_master`）で、根拠の無いイベントに
   任意フィールドが**付かない**こと。
2. 実際に公開されている `data/public/events_public.json` が、いまも疎であること。
   全イベントが同じキー集合を持つようになったら、それは1が壊れた結果である。
"""

import json
import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from export_public_events import build_public_events_from_master

# 既存のテストが持つ最小スキーマ生成を借りる。
# クラス名を自分の名前空間へ束縛すると pytest が二重に収集するため、モジュールごと参照する。
import test_export_public_events as export_fixtures


REPO_ROOT = Path(__file__).resolve().parents[1]
PUBLIC_JSON = REPO_ROOT / "data" / "public" / "events_public.json"

# 「確からしさに応じて付く」フィールド群。イベントごとに付いたり付かなかったりするのが正常。
OPTIONAL_FIELD_FAMILIES = {
    "季節ヒント": [
        "season_hint",
        "season_hint_label",
        "season_months",
        "season_confidence",
        "season_jun",
    ],
    "日付予測": [
        "date_prediction",
        "predicted_date",
        "predicted_date_end",
        "prediction_basis",
        "prediction_confidence",
        "prediction_evidence_years",
    ],
    "前年からのずらし": [
        "historical_slide",
        "historical_slide_date",
        "historical_slide_date_end",
        "historical_slide_method",
        "historical_slide_basis",
    ],
    "過去実績の参考": [
        "historical_reference",
        "historical_reference_label",
        "historical_reference_score",
        "historical_reference_confidence",
        "historical_last_seen_year",
        "historical_last_seen_dates",
        "historical_display_tier",
    ],
}

ALL_OPTIONAL_FIELDS = [
    name for fields in OPTIONAL_FIELD_FAMILIES.values() for name in fields
]


def _load_public_events():
    payload = json.loads(PUBLIC_JSON.read_text(encoding="utf-8"))
    return payload["events"] if isinstance(payload, dict) else payload


class BareOccurrenceKeepsFieldsAbsentTest(unittest.TestCase):
    """根拠の無いイベントに、任意フィールドを付けて回らないこと。"""

    def _build_bare_event(self):
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "master.sqlite"
            conn = sqlite3.connect(db)
            try:
                export_fixtures.ExportPublicEventsTest._create_minimal_master_export_schema(
                    None, conn
                )
                conn.execute(
                    "INSERT INTO event_series VALUES "
                    "('ser_1', '根拠の無い盆踊り', '[8]', NULL, 'active')"
                )
                conn.execute(
                    "INSERT INTO venues VALUES "
                    "('ven_1', '根拠の無い公園', '江東区', '小', '', '', '', '', "
                    "NULL, NULL, 'active')"
                )
                conn.execute(
                    """
                    INSERT INTO event_occurrences VALUES (
                      'occ_1', 'ser_1', 'ven_1', '根拠の無い盆踊り',
                      2026, NULL, NULL, 'unknown', 'published',
                      'medium', '', '', NULL, '',
                      'curated'
                    )
                    """
                )
                conn.commit()
            finally:
                conn.close()

            events, _, _, _ = build_public_events_from_master(db, target_year=2026)

        self.assertEqual(len(events), 1)
        return events[0]

    def test_bare_occurrence_omits_every_optional_field(self):
        event = self._build_bare_event()

        present = sorted(name for name in ALL_OPTIONAL_FIELDS if name in event)
        # 空文字や None で埋めるのも「埋めた」に入る。キーごと無いのが正しい。
        self.assertEqual(
            present,
            [],
            "根拠が無いのに任意フィールドが付いている。"
            "推測値で穴埋めすると、確定と推測の区別が公開JSONから失われる: %s" % present,
        )

    def test_bare_occurrence_still_carries_the_identity_fields(self):
        event = self._build_bare_event()

        # 欠けてよいのは任意フィールドだけで、同一性まで欠けてよいわけではない。
        for required in ("name", "venue"):
            self.assertIn(required, event)


class PublishedPublicJsonIsSparseTest(unittest.TestCase):
    """公開されている実物が、いまも疎であること。"""

    @classmethod
    def setUpClass(cls):
        cls.events = _load_public_events()
        cls.key_sets = [set(event.keys()) for event in cls.events]
        cls.union = set().union(*cls.key_sets)
        cls.intersection = set.intersection(*cls.key_sets)

    def test_public_json_has_fields_that_only_some_events_carry(self):
        optional = self.union - self.intersection
        self.assertGreater(
            len(optional),
            0,
            "全イベントが同じキー集合を持っている。"
            "どのイベントも全フィールドを埋める作りに変わった可能性がある。",
        )

    def test_no_single_event_carries_every_field(self):
        # 59フィールドは和集合であって、1件が全部持つことは無い、というのが仕様の主張。
        for event in self.events:
            self.assertLess(
                len(set(event.keys())),
                len(self.union),
                "1件のイベントが全フィールドを持っている: %s / %s"
                % (event.get("name"), event.get("venue")),
            )

    def test_each_optional_family_is_absent_from_some_event(self):
        for family, fields in OPTIONAL_FIELD_FAMILIES.items():
            in_union = [name for name in fields if name in self.union]
            self.assertTrue(
                in_union,
                "%s のフィールドが公開JSONから丸ごと消えている: %s" % (family, fields),
            )
            for name in in_union:
                missing_somewhere = any(name not in keys for keys in self.key_sets)
                self.assertTrue(
                    missing_somewhere,
                    "%s の %s が全イベントに付いている。"
                    "根拠の無いイベントまで埋めていないか確認が要る。" % (family, name),
                )


if __name__ == "__main__":
    unittest.main()
