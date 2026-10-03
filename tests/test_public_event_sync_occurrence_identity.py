import unittest

from guard_site_public_event_additions import classify_addition_diff
from sync_public_event_additions_to_site import build_site_events as build_additions, selected_collector_events
from sync_public_event_detail_source_to_site import build_site_events as build_detail
from sync_public_event_songs_to_site import build_site_events as build_songs
from sync_public_event_source_urls_to_site import build_site_events as build_sources


def event(occurrence_id, year, **extra):
    row = {"name": "同名盆踊り", "venue": "同じ会場", "occurrence_id": occurrence_id, "event_year": year}
    row.update(extra)
    return row


class PublicEventSyncOccurrenceIdentityTest(unittest.TestCase):
    def test_writers_update_the_matching_id_without_overwriting_same_name_venue(self):
        collector = [
            event("occ_2025", 2025, songs=[{"name": "旧曲"}], detail="old", source_urls=[{"url": "https://old"}]),
            event("occ_2026", 2026, songs=[{"name": "新曲"}], detail="new", source_urls=[{"url": "https://new"}]),
        ]
        site = [
            event("occ_2025", 2025, songs=[], detail="", source_urls=[]),
            event("occ_2026", 2026, songs=[], detail="", source_urls=[]),
        ]
        detail, rows = build_detail(collector, site, None)
        songs, _, _ = build_songs(collector, site)
        sources, _, _ = build_sources(collector, site)
        self.assertEqual([row["detail"] for row in detail], ["old", "new"])
        self.assertEqual([row["songs"] for row in songs], [[{"name": "旧曲"}], [{"name": "新曲"}]])
        self.assertEqual([row["source_urls"] for row in sources], [[{"url": "https://old"}], [{"url": "https://new"}]])
        self.assertEqual({row["event_key"] for row in rows}, {"occurrence:occ_2025", "occurrence:occ_2026"})

    def test_different_ids_never_bridge_by_legacy_alias(self):
        collector = [event("occ_collector", 2026, songs=[{"name": "collector"}], detail="collector", source_urls=[{"url": "https://collector"}])]
        site = [event("occ_site", 2026, songs=[], detail="site", source_urls=[])]
        detail, rows = build_detail(collector, site, None)
        songs, _, missing_songs = build_songs(collector, site)
        sources, source_rows, missing_sources = build_sources(collector, site)
        self.assertEqual(detail, site); self.assertEqual(rows, [])
        self.assertEqual(songs, site); self.assertEqual(missing_songs, ["occurrence:occ_collector"])
        self.assertEqual(sources, site); self.assertEqual(source_rows, [])
        self.assertEqual(missing_sources, ["同名盆踊り␟同じ会場"])

    def test_ambiguous_legacy_alias_and_allowed_legacy_key_are_rejected(self):
        collector = [event("occ_a", 2025, detail="a"), event("occ_b", 2026, detail="b")]
        site = [event("occ_a", 2025, detail=""), event("occ_b", 2026, detail="")]
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            build_detail(collector, site, {"同名盆踊り␟同じ会場"})
        detail, rows = build_detail(collector, site, {"occurrence:occ_b"})
        self.assertEqual([row["detail"] for row in detail], ["", "b"])
        self.assertEqual(len(rows), 1)

    def test_unique_legacy_allowed_key_remains_compatible(self):
        collector = [event("occ_a", 2026, detail="updated")]
        site = [event("occ_a", 2026, detail="")]
        detail, rows = build_detail(collector, site, {"同名盆踊り␟同じ会場"})
        self.assertEqual(detail[0]["detail"], "updated")
        self.assertEqual(rows[0]["event_key"], "occurrence:occ_a")

    def test_additions_require_explicit_id_for_ambiguous_name_and_replace_by_id(self):
        collector = [event("occ_a", 2025), event("occ_b", 2026)]
        selected, missing, ambiguous = selected_collector_events(collector, ["同名盆踊り"])
        self.assertEqual(selected, []); self.assertEqual(missing, []); self.assertEqual(ambiguous, ["同名盆踊り"])
        selected, missing, ambiguous = selected_collector_events(collector, [], ["occ_b"])
        self.assertEqual([row["occurrence_id"] for row in selected], ["occ_b"])
        self.assertEqual(missing, []); self.assertEqual(ambiguous, [])
        base = [event("occ_a", 2025, detail="base")]
        proposed = build_additions(base, [event("occ_b", 2026), event("occ_a", 2025, detail="replacement")])
        self.assertEqual([row["occurrence_id"] for row in proposed], ["occ_b", "occ_a"])
        self.assertEqual(proposed[1]["detail"], "replacement")

    def test_guard_keeps_different_ids_as_add_remove(self):
        diff = classify_addition_diff([event("occ_a", 2025)], [event("occ_b", 2026)])
        self.assertEqual([row["occurrence_id"] for row in diff["added"]], ["occ_b"])
        self.assertEqual([row["occurrence_id"] for row in diff["removed"]], ["occ_a"])
        self.assertEqual(diff["modified"], [])


if __name__ == "__main__":
    unittest.main()
