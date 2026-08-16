import argparse
import inspect
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from master_rdb.master_db import file_sha256, init_db, normalize_text, stable_id
from report_apply.apply_x_song_identity_results import apply_results, run
from report_apply.event_report_helpers import upsert_evidence_item, upsert_occurrence_song
from review_inbox_adapters.build_x_song_identity_packets import build
from review_inbox_adapters.x_song_identity_contract import candidate_ids_sha256
from review_inbox_adapters.x_song_identity_contract import occurrence_candidates, song_candidates


NOW = datetime(2026, 8, 16, 12, tzinfo=timezone.utc)
STAMP = NOW.isoformat()


class E2SSongIdentityTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = self.root / "master.sqlite"
        self.conn = init_db(self.db)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute(
            """
            INSERT INTO songs(song_id, canonical_title, normalized_title, status, created_at, updated_at)
            VALUES ('song_tanko', '炭坑節', ?, '候補', ?, ?)
            """,
            (normalize_text("炭坑節"), STAMP, STAMP),
        )
        self.conn.execute(
            """
            INSERT INTO song_aliases(song_id, alias, normalized_alias, source, confidence)
            VALUES ('song_tanko', '炭鉱節', ?, 'manual', 'manual')
            """,
            (normalize_text("炭鉱節"),),
        )
        self.conn.execute(
            """
            INSERT INTO event_series(
              series_id, origin, series_key, canonical_name, normalized_name,
              status, created_at, updated_at
            ) VALUES ('series_test', 'curated', ?, '試験盆踊り', ?, 'active', ?, ?)
            """,
            (normalize_text("試験盆踊り"), normalize_text("試験盆踊り"), STAMP, STAMP),
        )
        self.conn.execute(
            """
            INSERT INTO event_occurrences(
              occurrence_id, origin, series_id, event_year, occurrence_sequence,
              display_name, date_start, date_end, date_status, lifecycle_status,
              current_event_state, date_certainty_tier, confidence, created_at, updated_at
            ) VALUES (
              'occ_test', 'curated', 'series_test', 2026, 1, '試験盆踊り 2026',
              '2026-08-20', '2026-08-20', 'confirmed', 'published',
              'confirmed', 'confirmed', 'high', ?, ?
            )
            """,
            (STAMP, STAMP),
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        self.temp.cleanup()

    def observation(self, suffix="1", **extra):
        row = {
            "observation_id": f"xsong_{suffix}",
            "tweet_id": f"tweet_{suffix}",
            "url": f"https://x.example/status/{suffix}",
            "posted_at": "2026-08-15T03:00:00+00:00",
            "account": "@tester",
            "officiality": "unknown_or_personal_social",
            "event_name": "試験盆踊り",
            "song_name": "炭鉱節",
            "origin": "observations",
            "batch_id": "x_extract_001",
            "score": 4,
            "text": "試験盆踊りで炭鉱節を踊った",
            "first_seen_at": STAMP,
        }
        row.update(extra)
        return row

    def packet(self, observation=None, state=None):
        observation = observation or self.observation()
        report = build(
            self.conn,
            {"observations": [observation]},
            state or {},
            when=NOW,
        )
        self.assertEqual(report["issues"], [])
        return report["packets"][0]

    def answer(self, packet, **extra):
        result = {
            "packet_id": packet["packet_id"],
            "observation_id": packet["observation_id"],
            "song_match": "song_tanko",
            "occurrence_match": "occ_test",
            "reason": "別名と開催回が一致",
        }
        result.update(extra)
        return result

    def apply(self, observations, packets, results, state=None):
        packet_index = {packet["packet_id"]: packet for packet in packets}
        return apply_results(
            self.conn,
            packet_index,
            results,
            {"observations": observations},
            state or {},
            when=NOW,
        )

    # 1. 開催回が決まれば occurrence_songs へ届く。
    def test_acceptance_01_existing_occurrence_creates_occurrence_song(self):
        observation = self.observation()
        packet = self.packet(observation)
        report, _ = self.apply([observation], [packet], [self.answer(packet)])
        self.assertEqual(report["applied"], 1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM occurrence_songs").fetchone()[0], 1)

    # 2. occurrence none は決して書かない。
    def test_acceptance_02_occurrence_none_writes_nothing(self):
        observation = self.observation()
        packet = self.packet(observation)
        report, _ = self.apply(
            [observation], [packet], [self.answer(packet, occurrence_match="none")]
        )
        self.assertEqual((report["deferred"], self.conn.execute("SELECT COUNT(*) FROM occurrence_songs").fetchone()[0]), (1, 0))

    # 3. 曲候補 none は由来つき新曲になる。
    def test_acceptance_03_song_none_registers_active_song_and_occurrence_song(self):
        observation = self.observation(song_name="新作音頭", text="試験盆踊りで新作音頭を踊った")
        packet = self.packet(observation)
        report, _ = self.apply([observation], [packet], [self.answer(packet, song_match="none")])
        self.assertEqual(report["applied"], 1)
        row = self.conn.execute("SELECT status FROM songs WHERE canonical_title='新作音頭'").fetchone()
        self.assertEqual(row[0], "active")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM occurrence_songs").fetchone()[0], 1)

    # 4. 新曲は必ず source_url と memo を持つ。
    def test_acceptance_04_all_new_songs_have_provenance(self):
        observation = self.observation(song_name="新作音頭", text="試験盆踊りで新作音頭を踊った")
        packet = self.packet(observation)
        self.apply([observation], [packet], [self.answer(packet, song_match="none")])
        row = self.conn.execute("SELECT source_url,memo FROM songs WHERE canonical_title='新作音頭'").fetchone()
        self.assertTrue(row["source_url"])
        self.assertIn(observation["observation_id"], row["memo"])
        self.assertIn(observation["batch_id"], row["memo"])

    # 4b. 既存曲の状態は昇格しない。
    def test_acceptance_04b_existing_song_status_is_unchanged(self):
        observation = self.observation()
        packet = self.packet(observation)
        self.apply([observation], [packet], [self.answer(packet)])
        self.assertEqual(self.conn.execute("SELECT status FROM songs WHERE song_id='song_tanko'").fetchone()[0], "候補")

    # 4c. 同じ新曲を同じバッチで2回読んでも master は1行。
    def test_acceptance_04c_duplicate_new_song_is_registered_once(self):
        observations = [
            self.observation("1", song_name="新作音頭", text="試験盆踊りで新作音頭"),
            self.observation("2", song_name="新作音頭", text="試験盆踊りで新作音頭"),
        ]
        packets = [self.packet(row) for row in observations]
        answers = [self.answer(packet, song_match="none") for packet in packets]
        self.apply(observations, packets, answers)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM songs WHERE canonical_title='新作音頭'").fetchone()[0], 1)

    # 5. events は announced/prediction。
    def test_acceptance_05_events_origin_maps_to_announced_prediction(self):
        observation = self.observation(origin="events")
        packet = self.packet(observation)
        self.apply([observation], [packet], [self.answer(packet)])
        row = self.conn.execute("SELECT evidence_status,role FROM occurrence_songs").fetchone()
        self.assertEqual(tuple(row), ("announced", "prediction"))

    # 6. observations は observed/result。
    def test_acceptance_06_observations_origin_maps_to_observed_result(self):
        observation = self.observation()
        packet = self.packet(observation)
        self.apply([observation], [packet], [self.answer(packet)])
        row = self.conn.execute("SELECT evidence_status,role FROM occurrence_songs").fetchone()
        self.assertEqual(tuple(row), ("observed", "result"))

    # 7. LLM の evidence_status は採用しない。
    def test_acceptance_07_ignores_llm_evidence_status(self):
        observation = self.observation(origin="events")
        packet = self.packet(observation)
        self.apply([observation], [packet], [self.answer(packet, evidence_status="observed")])
        self.assertEqual(self.conn.execute("SELECT evidence_status FROM occurrence_songs").fetchone()[0], "announced")

    # 8. 見せていないIDは拒否。
    def test_acceptance_08_rejects_id_outside_candidates(self):
        observation = self.observation()
        packet = self.packet(observation)
        report, _ = self.apply([observation], [packet], [self.answer(packet, song_match="song_unseen")])
        self.assertEqual(report["rejected_result"], 1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM occurrence_songs").fetchone()[0], 0)

    # 9. 候補集合が変わった回答は stale。
    def test_acceptance_09_candidate_set_change_is_stale(self):
        observation = self.observation(song_name="新作音頭", text="試験盆踊りで新作音頭")
        packet = self.packet(observation)
        self.conn.execute(
            "INSERT INTO songs(song_id,canonical_title,normalized_title,status,created_at,updated_at) VALUES ('song_new','新作音頭',?,'active',?,?)",
            (normalize_text("新作音頭"), STAMP, STAMP),
        )
        report, _ = self.apply([observation], [packet], [self.answer(packet, song_match="none")])
        self.assertEqual(report["stale"], 1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM occurrence_songs").fetchone()[0], 0)

    # 10. event_name null は開催回候補ゼロ。
    def test_acceptance_10_null_event_name_has_no_occurrence_candidates(self):
        packet = self.packet(self.observation(event_name=None))
        self.assertEqual(packet["occurrence_candidates"], [])

    # 11. 再取り込みは occurrence_songs を増やさない。
    def test_acceptance_11_occurrence_song_is_idempotent(self):
        observation = self.observation()
        packet = self.packet(observation)
        answer = self.answer(packet)
        self.apply([observation], [packet], [answer])
        self.apply([observation], [packet], [answer])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM occurrence_songs").fetchone()[0], 1)

    # 12. 新しい由来語彙を固定。
    def test_acceptance_12_occurrence_song_origin_is_observed_x_post(self):
        observation = self.observation()
        packet = self.packet(observation)
        self.apply([observation], [packet], [self.answer(packet)])
        self.assertEqual(self.conn.execute("SELECT origin FROM occurrence_songs").fetchone()[0], "observed_x_post")

    # 13. dry-run は master RDB を変更しない。
    def test_acceptance_13_dry_run_preserves_master_checksum(self):
        observation = self.observation()
        packet = self.packet(observation)
        batch = self.root / "batch.json"
        answer = self.root / "answer.json"
        ledger = self.root / "observations.json"
        state = self.root / "state.json"
        batch.write_text(json.dumps({"batch_id": "b", "packets": [packet]}, ensure_ascii=False))
        answer.write_text(json.dumps({"results": [self.answer(packet)]}, ensure_ascii=False))
        ledger.write_text(json.dumps({"observations": [observation]}, ensure_ascii=False))
        state.write_text("{}\n")
        self.conn.commit()
        before = file_sha256(self.db)
        args = argparse.Namespace(
            db=self.db,
            observations=ledger,
            state=state,
            packets=[batch],
            results=[answer],
            out_db=self.root / "dry.sqlite",
            report_json=self.root / "report.json",
            report_md=self.root / "report.md",
            preflight_db=self.root / "preflight.sqlite",
            backup_dir=self.root / "backups",
            apply=False,
            confirm="",
        )
        output = run(args)
        self.assertTrue(output["master_checksum_unchanged"])
        self.assertEqual(file_sha256(self.db), before)

    # 14. applied は再発行しない。
    def test_acceptance_14_applied_state_is_not_reissued(self):
        observation = self.observation()
        state = {observation["observation_id"]: {"outcome": "applied"}}
        self.assertEqual(build(self.conn, {"observations": [observation]}, state, when=NOW)["generated"], 0)

    # 15. deferred は30日後に再評価。
    def test_acceptance_15_deferred_reissues_after_thirty_days(self):
        observation = self.observation()
        packet = self.packet(observation)
        _report, state = self.apply(
            [observation], [packet], [self.answer(packet, occurrence_match="none")]
        )
        self.assertEqual(build(self.conn, {"observations": [observation]}, state, when=NOW + timedelta(days=29))["generated"], 0)
        self.assertEqual(build(self.conn, {"observations": [observation]}, state, when=NOW + timedelta(days=30))["generated"], 1)

    # 16. helper の任意引数は旧既定値を明示的に保持。
    def test_acceptance_16_helper_defaults_preserve_legacy_contract(self):
        signature = inspect.signature(upsert_occurrence_song)
        self.assertIsNone(signature.parameters["song_id"].default)
        self.assertEqual(signature.parameters["origin"].default, "curated")
        self.assertIsNone(signature.parameters["song_source_url"].default)
        self.assertIsNone(signature.parameters["song_memo"].default)
        evidence_id = stable_id("ev", "legacy-default")
        upsert_evidence_item(
            self.conn,
            evidence_id,
            platform="web",
            evidence_type="poster_post",
            source_key="legacy",
            text_excerpt="新曲告知",
            now=STAMP,
        )
        applied = upsert_occurrence_song(
            self.conn,
            "occ_test",
            "旧既定値音頭",
            evidence_id,
            role="setlist",
            evidence_status="announced",
            basis_key="official_notice",
            evidence_note="告知",
            now=STAMP,
        )
        song = self.conn.execute("SELECT source_url,memo,status FROM songs WHERE song_id=?", (applied["song_id"],)).fetchone()
        occurrence = self.conn.execute("SELECT origin,confidence FROM occurrence_songs WHERE occurrence_song_id=?", (applied["occurrence_song_id"],)).fetchone()
        self.assertEqual(tuple(song), (None, None, "active"))
        self.assertEqual(tuple(occurrence), ("curated", "high"))

    # 17. 別名で既存IDを選んでも新曲は作らない。
    def test_acceptance_17_alias_match_with_explicit_id_does_not_create_song(self):
        observation = self.observation()
        packet = self.packet(observation)
        self.assertEqual(packet["song_candidates"][0]["matched_alias"], "炭鉱節")
        before = self.conn.execute("SELECT COUNT(*) FROM songs").fetchone()[0]
        self.apply([observation], [packet], [self.answer(packet)])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM songs").fetchone()[0], before)

    # 18. occurrence_songs には canonical_title を書く。
    def test_acceptance_18_existing_song_writes_canonical_title(self):
        observation = self.observation()
        packet = self.packet(observation)
        self.apply([observation], [packet], [self.answer(packet)])
        self.assertEqual(self.conn.execute("SELECT song_title_raw FROM occurrence_songs").fetchone()[0], "炭坑節")

    # 19. 同じ既存曲の別表記でも1行。
    def test_acceptance_19_two_spellings_of_same_song_create_one_occurrence_song(self):
        observations = [self.observation("1"), self.observation("2", song_name="炭坑節", text="試験盆踊りで炭坑節")]
        packets = [self.packet(row) for row in observations]
        self.apply(observations, packets, [self.answer(packet) for packet in packets])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM occurrence_songs").fetchone()[0], 1)

    # 20. evidence を先に作り、リンクのFKを満たす。
    def test_acceptance_20_evidence_and_link_are_created(self):
        observation = self.observation()
        packet = self.packet(observation)
        self.apply([observation], [packet], [self.answer(packet)])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM evidence_items").fetchone()[0], 1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM occurrence_song_evidence_links").fetchone()[0], 1)
        self.assertEqual(self.conn.execute("PRAGMA foreign_key_check").fetchall(), [])

    # 21. evidence_id は observation_id から決まり冪等。
    def test_acceptance_21_evidence_is_idempotent(self):
        observation = self.observation()
        packet = self.packet(observation)
        answer = self.answer(packet)
        self.apply([observation], [packet], [answer])
        self.apply([observation], [packet], [answer])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM evidence_items").fetchone()[0], 1)
        self.assertEqual(self.conn.execute("SELECT evidence_id FROM evidence_items").fetchone()[0], stable_id("ev", "x_song", observation["observation_id"]))

    # 22. raw_json には投稿の生表記を残す。
    def test_acceptance_22_evidence_keeps_raw_song_spelling(self):
        observation = self.observation()
        packet = self.packet(observation)
        self.apply([observation], [packet], [self.answer(packet)])
        raw = json.loads(self.conn.execute("SELECT raw_json FROM evidence_items").fetchone()[0])
        self.assertEqual(raw["song_name"], "炭鉱節")

    # 23. 空URLは tweet_id から復元し memo に注記。
    def test_acceptance_23_reconstructs_empty_url_and_marks_memo(self):
        observation = self.observation(url="", song_name="新作音頭", text="試験盆踊りで新作音頭")
        packet = self.packet(observation)
        self.apply([observation], [packet], [self.answer(packet, song_match="none")])
        row = self.conn.execute("SELECT source_url,memo FROM songs WHERE canonical_title='新作音頭'").fetchone()
        self.assertEqual(row["source_url"], "https://x.com/i/status/tweet_1")
        self.assertIn("reconstructed_from_tweet_id", row["memo"])

    # 24. confidence は件数で変えず常に high。
    def test_acceptance_24_confidence_is_high_for_one_or_two_observations(self):
        one = self.observation("1")
        packet_one = self.packet(one)
        self.apply([one], [packet_one], [self.answer(packet_one)])
        self.assertEqual(self.conn.execute("SELECT confidence FROM occurrence_songs").fetchone()[0], "high")
        two = self.observation("2")
        packet_two = self.packet(two)
        self.apply([two], [packet_two], [self.answer(packet_two)])
        self.assertEqual(self.conn.execute("SELECT confidence FROM occurrence_songs").fetchone()[0], "high")

    # 25. stale は next_eligible_at を持たず即再発行。
    def test_acceptance_25_stale_is_immediately_reissued(self):
        observation = self.observation(song_name="新作音頭", text="試験盆踊りで新作音頭")
        packet = self.packet(observation)
        self.conn.execute(
            "INSERT INTO songs(song_id,canonical_title,normalized_title,status,created_at,updated_at) VALUES ('song_new','新作音頭',?,'active',?,?)",
            (normalize_text("新作音頭"), STAMP, STAMP),
        )
        _report, state = self.apply([observation], [packet], [self.answer(packet, song_match="none")])
        row = state[observation["observation_id"]]
        self.assertEqual(row["outcome"], "stale")
        self.assertNotIn("next_eligible_at", row)
        self.assertEqual(build(self.conn, {"observations": [observation]}, state, when=NOW)["generated"], 1)

    # 26. dry-run は state ファイルも変更しない。
    def test_acceptance_26_dry_run_does_not_write_state(self):
        observation = self.observation()
        packet = self.packet(observation)
        batch = self.root / "batch.json"
        answer = self.root / "answer.json"
        ledger = self.root / "observations.json"
        state = self.root / "state.json"
        batch.write_text(json.dumps({"packets": [packet]}, ensure_ascii=False))
        answer.write_text(json.dumps({"results": [self.answer(packet)]}, ensure_ascii=False))
        ledger.write_text(json.dumps({"observations": [observation]}, ensure_ascii=False))
        state.write_text('{"sentinel":{"outcome":"stale"}}\n')
        self.conn.commit()
        before = state.read_bytes()
        run(argparse.Namespace(
            db=self.db, observations=ledger, state=state, packets=[batch], results=[answer],
            out_db=self.root / "dry.sqlite", report_json=self.root / "report.json",
            report_md=self.root / "report.md", preflight_db=self.root / "preflight.sqlite",
            backup_dir=self.root / "backups", apply=False, confirm="",
        ))
        self.assertEqual(state.read_bytes(), before)

    # 27. 表示情報が変わってもID列が同じなら stale ではない。
    def test_acceptance_27_candidate_hash_uses_only_ordered_ids(self):
        self.assertEqual(
            candidate_ids_sha256(["song_a", "song_b"]),
            candidate_ids_sha256(["song_a", "song_b"]),
        )
        observation = self.observation()
        packet = self.packet(observation)
        self.conn.execute("UPDATE songs SET canonical_title='炭坑節（表示改訂）',status='active' WHERE song_id='song_tanko'")
        report, _ = self.apply([observation], [packet], [self.answer(packet)])
        self.assertEqual(report["stale"], 0)
        self.assertEqual(report["applied"], 1)

    def test_song_candidates_order_exact_prefix_substring_then_song_id(self):
        for song_id, title in (
            ("song_a", "試験音頭"),
            ("song_b", "試験音頭二番"),
            ("song_c", "大試験音頭大会"),
        ):
            self.conn.execute(
                "INSERT INTO songs(song_id,canonical_title,normalized_title,status,created_at,updated_at) VALUES (?,?,?,'active',?,?)",
                (song_id, title, normalize_text(title), STAMP, STAMP),
            )
        rows = song_candidates(self.conn, "試験音頭")
        self.assertEqual([row["song_id"] for row in rows], ["song_a", "song_b", "song_c"])
        self.assertEqual([row["match_type"] for row in rows], ["exact", "prefix", "substring"])

    def test_occurrence_candidates_break_ties_by_newest_date_then_id(self):
        for suffix, date_start in (("a", "2026-08-19"), ("b", "2026-08-21"), ("c", "2026-08-21")):
            self.conn.execute(
                """
                INSERT INTO event_occurrences(
                  occurrence_id,origin,series_id,event_year,occurrence_sequence,display_name,
                  date_start,date_end,date_status,lifecycle_status,current_event_state,
                  date_certainty_tier,confidence,created_at,updated_at
                ) VALUES (?, 'curated','series_test',2026,?,'試験盆踊り',?,?,'confirmed','published',
                          'confirmed','confirmed','high',?,?)
                """,
                (f"occ_{suffix}", len(suffix) + {"a": 1, "b": 2, "c": 3}[suffix], date_start, date_start, STAMP, STAMP),
            )
        rows = occurrence_candidates(self.conn, "試験盆踊り")
        ids = [row["occurrence_id"] for row in rows]
        self.assertLess(ids.index("occ_b"), ids.index("occ_c"))
        self.assertLess(ids.index("occ_c"), ids.index("occ_a"))


if __name__ == "__main__":
    unittest.main()
