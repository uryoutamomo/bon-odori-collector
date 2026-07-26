import unittest

from event_model.event_series_normalization import (
    public_series_name,
    series_event_name,
    strip_occurrence_edition,
)


class EventSeriesNormalizationTest(unittest.TestCase):
    def test_strips_edition_counter(self):
        self.assertEqual(strip_occurrence_edition("第7回 渋谷盆踊り"), "渋谷盆踊り")
        self.assertEqual(strip_occurrence_edition("第16回ハマサイトの夏祭り"), "ハマサイトの夏祭り")
        self.assertEqual(strip_occurrence_edition("地域のふれあい第37回盆踊り大会"), "地域のふれあい盆踊り大会")
        self.assertEqual(strip_occurrence_edition("砧小学校「第38回砧っ子夏祭り」"), "砧小学校「砧っ子夏祭り」")
        self.assertEqual(strip_occurrence_edition("第２回 辰巳で盆踊り"), "辰巳で盆踊り")

    def test_keeps_names_without_edition_counter(self):
        for name in ["渋谷盆踊り", "盆踊 〜BONDO〜", "丸の内de盆踊り", "回向院大盆踊り"]:
            self.assertEqual(strip_occurrence_edition(name), name)

    def test_never_returns_empty_name(self):
        self.assertEqual(strip_occurrence_edition("第7回"), "第7回")

    def test_series_event_name_still_keeps_edition_for_series_identity(self):
        # series_key is derived from series_event_name; renaming what readers see
        # must not renumber RDB series ids.
        self.assertEqual(series_event_name("第7回 渋谷盆踊り 2026"), "第7回 渋谷盆踊り")

    def test_public_series_name_drops_year_and_edition(self):
        self.assertEqual(public_series_name("第7回 渋谷盆踊り 2026"), "渋谷盆踊り")
        self.assertEqual(public_series_name("第16回 鴨台盆踊り"), "鴨台盆踊り")


if __name__ == "__main__":
    unittest.main()
