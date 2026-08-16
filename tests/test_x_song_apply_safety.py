import sqlite3

import pytest

from master_rdb.master_db import init_db
from report_apply.x_song_apply_safety import run_guarded


NOW = "2026-08-16T00:00:00+00:00"


def test_execute_has_backup_and_rolls_back_when_final_verification_fails(tmp_path):
    db = tmp_path / "master.sqlite"
    conn = init_db(db)
    conn.commit()
    conn.close()
    calls = 0

    def operation(conn):
        nonlocal calls
        calls += 1
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            INSERT INTO evidence_items (
              evidence_id, platform, evidence_type, source_key, raw_json
            ) VALUES (?, 'x', 'test', 'test', '{}')
            """,
            (f"evidence_{calls}",),
        )
        if calls == 2:
            conn.execute("PRAGMA defer_foreign_keys = ON")
            conn.execute(
                """
                INSERT INTO occurrence_songs (
                  occurrence_song_id, occurrence_id, song_title_raw, normalized_title,
                  role, evidence_status, confidence, created_at, updated_at
                ) VALUES ('bad_fact', 'missing_occurrence', '曲', '曲',
                          'result', 'observed', 'high', ?, ?)
                """,
                (NOW, NOW),
            )
        return {"call": calls}

    with pytest.raises(ValueError, match="foreign_keys"):
        run_guarded(
            db_path=db,
            execute=True,
            timestamp=NOW,
            temp_prefix="safety-test-",
            operation=operation,
            backup_dir=tmp_path / "backups",
        )

    with sqlite3.connect(db) as check:
        assert check.execute("SELECT COUNT(*) FROM evidence_items").fetchone()[0] == 0
        assert check.execute("SELECT COUNT(*) FROM occurrence_songs").fetchone()[0] == 0
    backups = list((tmp_path / "backups").glob("*.bak"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as backup:
        assert backup.execute("SELECT COUNT(*) FROM evidence_items").fetchone()[0] == 0
