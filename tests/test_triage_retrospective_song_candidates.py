import json
import subprocess
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

from song_processing.song_catalog import SongCatalog
from legacy.retrospective_tools.triage_retrospective_song_candidates import (
    classify_retrospective,
    triage,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def make_db():
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE songs (
          song_id TEXT PRIMARY KEY,
          canonical_title TEXT NOT NULL,
          normalized_title TEXT NOT NULL UNIQUE,
          status TEXT NOT NULL DEFAULT 'active'
        );
        CREATE TABLE song_aliases (
          song_id TEXT NOT NULL,
          alias TEXT NOT NULL,
          normalized_alias TEXT NOT NULL,
          source TEXT NOT NULL,
          confidence TEXT NOT NULL DEFAULT 'manual',
          PRIMARY KEY (song_id, normalized_alias)
        );
        """
    )
    return conn


def insert_song(conn, song_id, title, status="active"):
    conn.execute(
        "INSERT INTO songs(song_id, canonical_title, normalized_title, status) "
        "VALUES (?, ?, ?, ?)",
        (song_id, title, title, status),
    )


class TriageRetrospectiveSongCandidatesTest(unittest.TestCase):
    """Smoke coverage for the P2 fix: classify_candidate() now requires a
    catalog argument, and this legacy CLI must pass one through end to end
    without touching Notion, the network, or repo data files."""

    def setUp(self):
        self.conn = make_db()
        self.catalog = SongCatalog.from_connection(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_classify_retrospective_accepts_injected_catalog(self):
        candidate = {
            "kind": "song",
            "display_name": "東京音頭",
            "score": 60,
            "evidence_count": 3,
            "speaker_count": 2,
        }
        bucket, canonical, reason = classify_retrospective(candidate, {}, self.catalog)

        self.assertEqual(bucket, "new_song_candidate")
        self.assertEqual(canonical, "東京音頭")

    def test_triage_end_to_end_with_injected_catalog(self):
        data = {
            "candidates": [
                {
                    "kind": "song",
                    "display_name": "東京音頭",
                    "score": 60,
                    "evidence_count": 3,
                    "speaker_count": 2,
                },
                {
                    "kind": "song",
                    "display_name": "またその行事内で行われる踊り",
                    "score": 10,
                },
                {"kind": "venue", "display_name": "この行は無視される"},
            ]
        }
        result = triage(data, {}, self.catalog)

        self.assertEqual(result["candidate_count"], 2)
        buckets = {row["raw_name"]: row["bucket"] for row in result["rows"]}
        self.assertEqual(buckets["東京音頭"], "new_song_candidate")
        self.assertEqual(buckets["またその行事内で行われる踊り"], "reject_noise")


class TriageRetrospectiveCliWiringTest(unittest.TestCase):
    """Runs the actual CLI entrypoint end to end against a temp DB and temp
    input/output files -- no Notion, no network, no repo data writes."""

    def _run(self, db_path, tmp_dir):
        source_path = Path(tmp_dir) / "source.json"
        source_path.write_text(
            json.dumps({"candidates": [{"kind": "song", "display_name": "東京音頭",
                                          "score": 60, "evidence_count": 3, "speaker_count": 2}]}),
            encoding="utf-8",
        )
        song_master_path = Path(tmp_dir) / "song_master.json"
        song_master_path.write_text("{}", encoding="utf-8")
        out_path = Path(tmp_dir) / "out.json"
        md_out_path = Path(tmp_dir) / "out.md"
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "legacy.retrospective_tools.triage_retrospective_song_candidates",
                "--source", str(source_path),
                "--song-master", str(song_master_path),
                "--out", str(out_path),
                "--md-out", str(md_out_path),
                "--db", str(db_path),
            ],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
        ), out_path

    def test_cli_succeeds_with_valid_db(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "master.sqlite"
            with sqlite3.connect(db_path) as file_conn:
                file_conn.executescript(
                    """
                    CREATE TABLE songs (
                      song_id TEXT PRIMARY KEY,
                      canonical_title TEXT NOT NULL,
                      normalized_title TEXT NOT NULL UNIQUE,
                      status TEXT NOT NULL DEFAULT 'active'
                    );
                    CREATE TABLE song_aliases (
                      song_id TEXT NOT NULL,
                      alias TEXT NOT NULL,
                      normalized_alias TEXT NOT NULL,
                      source TEXT NOT NULL,
                      confidence TEXT NOT NULL DEFAULT 'manual',
                      PRIMARY KEY (song_id, normalized_alias)
                    );
                    """
                )
                file_conn.execute(
                    "INSERT INTO songs(song_id, canonical_title, normalized_title, status) "
                    "VALUES ('song_1', '東京音頭', '東京音頭', 'active')"
                )
                file_conn.commit()

            proc, out_path = self._run(db_path, tmp_dir)

            self.assertEqual(proc.returncode, 0, proc.stderr)
            result = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(result["counts"].get("new_song_candidate"), 1)

    def test_cli_fails_explicitly_when_db_missing(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            missing_db = Path(tmp_dir) / "does-not-exist.sqlite"
            proc, _out_path = self._run(missing_db, tmp_dir)

            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("OperationalError", proc.stderr)


if __name__ == "__main__":
    unittest.main()
