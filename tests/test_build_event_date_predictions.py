import unittest

from youtube_backfill.build_event_date_predictions import build_predictions


def observation(series_key, event_name, venue, year, start, end=None):
    return {
        "observation_id": f"{series_key}-{year}-{start}",
        "series_key": series_key,
        "event_name": event_name,
        "venue": venue,
        "year": year,
        "date_start": start,
        "date_end": end or start,
        "weekday_start": "",
        "weekday_end": "",
        "source_video_count": 3,
        "source_channels": ["ch"],
        "confidence": "medium",
        "songs": [],
    }


def payload(rows):
    series = []
    seen = set()
    for row in rows:
        if row["series_key"] in seen:
            continue
        seen.add(row["series_key"])
        series.append({
            "series_key": row["series_key"],
            "canonical_name": row["event_name"],
            "usual_venue": row["venue"],
            "observed_years": sorted({item["year"] for item in rows if item["series_key"] == row["series_key"]}),
            "has_3year_window": False,
            "song_years": [],
        })
    return {"series": series, "observations": rows}


class BuildEventDatePredictionsTest(unittest.TestCase):
    def test_prefers_last_weekday_for_marunouchi_style(self):
        rows = [
            observation("s1", "丸の内de盆踊り", "行幸通り", 2024, "2024-07-26"),
            observation("s1", "丸の内de盆踊り", "行幸通り", 2025, "2025-07-25"),
        ]

        data = build_predictions(payload(rows), target_year=2026)
        pred = data["predictions"][0]["prediction"]

        self.assertEqual(pred["rule_type"], "weekday_last")
        self.assertEqual(pred["predicted_date_start"], "2026-07-31")
        self.assertEqual(pred["predicted_weekday_start"], "金")

    def test_uses_nth_weekday_for_shitamachi_style(self):
        rows = [
            observation("s1", "シタマチ.ふるさと盆踊り大会", "おかちまちパンダ広場", 2024, "2024-08-17"),
            observation("s1", "シタマチ.ふるさと盆踊り大会", "おかちまちパンダ広場", 2025, "2025-08-16"),
        ]

        data = build_predictions(payload(rows), target_year=2026)
        pred = data["predictions"][0]["prediction"]

        self.assertEqual(pred["rule_type"], "weekday_nth")
        self.assertEqual(pred["basis"], "8月第3土曜")
        self.assertEqual(pred["predicted_date_start"], "2026-08-15")

    def test_uses_weekday_near_day_when_nth_changes(self):
        rows = [
            observation("s1", "自由が丘納涼盆踊り大会", "自由が丘駅前ロータリー", 2024, "2024-07-13", "2024-07-15"),
            observation("s1", "自由が丘納涼盆踊り大会", "自由が丘駅前ロータリー", 2025, "2025-07-19", "2025-07-21"),
        ]

        data = build_predictions(payload(rows), target_year=2026)
        pred = data["predictions"][0]["prediction"]

        self.assertEqual(pred["rule_type"], "weekday_near_day")
        self.assertEqual(pred["predicted_date_start"], "2026-07-18")
        self.assertEqual(pred["predicted_date_end"], "2026-07-20")
        self.assertEqual(pred["predicted_weekday_start"], "土")
        self.assertEqual(pred["predicted_weekday_end"], "月")

    def test_falls_back_to_fixed_date_for_sanno_style(self):
        rows = [
            observation("s1", "山王音頭と民踊大会", "山王パークタワー公開空地", 2023, "2023-06-13"),
            observation("s1", "山王音頭と民踊大会", "山王パークタワー公開空地", 2024, "2024-06-13", "2024-06-15"),
        ]

        data = build_predictions(payload(rows), target_year=2026)
        pred = data["predictions"][0]["prediction"]

        self.assertEqual(pred["rule_type"], "fixed_date")
        self.assertEqual(pred["predicted_date_start"], "2026-06-13")
        self.assertEqual(pred["predicted_date_end"], "2026-06-15")

    def test_prefers_weekend_near_day_over_weak_fixed_date(self):
        rows = [
            observation("s1", "西久保八幡神社 盆踊り", "西久保八幡神社", 2023, "2023-08-10", "2023-08-12"),
            observation("s1", "西久保八幡神社 盆踊り", "西久保八幡神社", 2024, "2024-08-09"),
            observation("s1", "西久保八幡神社 盆踊り", "西久保八幡神社", 2025, "2025-08-09"),
        ]

        data = build_predictions(payload(rows), target_year=2026)
        pred = data["predictions"][0]["prediction"]

        self.assertEqual(pred["rule_type"], "weekend_near_day")
        self.assertEqual(pred["predicted_date_start"], "2026-08-08")
        self.assertEqual(pred["predicted_weekday_start"], "土")

    def test_builds_the_next_year_without_a_2026_default(self):
        rows = [
            observation("s1", "丸の内de盆踊り", "行幸通り", 2025, "2025-07-25"),
            observation("s1", "丸の内de盆踊り", "行幸通り", 2026, "2026-07-31"),
        ]

        data = build_predictions(payload(rows), target_year=2027)
        pred = data["predictions"][0]["prediction"]

        self.assertEqual(data["target_year"], 2027)
        self.assertEqual(pred["predicted_date_start"], "2027-07-30")


if __name__ == "__main__":
    unittest.main()
