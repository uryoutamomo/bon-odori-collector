# Firsthand field report apply result

- generated_at: 2026-07-12T15:01:26.301899+00:00
- mode: apply
- report_type: existing_event_songs
- resolved: True
- target_db: `data/bon_odori_master.sqlite`
- dry_run_db: ``
- backup_db: `data/backups/bon_odori_master.20260712T150126.301899+0000.sqlite.bak`
- db_committed: True
- rolled_back: False
- issues_by_severity: {}
- audit_issues_by_severity: {'medium': 1}

## Applied

- occurrence_id: `occ_46270bfba6367730`
- evidence_id: `ev_6d46838ea3311088`

### Songs

- osong_7e15cd608096a1d6 (song_id=song_242d9e37e1176744)
- osong_bbe0bab1914507e5 (song_id=song_49b79df0f91492e1)
- osong_3a24c29335de530c (song_id=song_4a0b4e35fdb1a42e)
- osong_a48f0a28bbd31a60 (song_id=song_ba38e97046254d94)
- osong_1fdeae725029d761 (song_id=song_2db09070cee96f09)
- osong_8ca1fa3e0abc71fc (song_id=song_8301ef2fd9b554f0)
- osong_063e91c0a6117f16 (song_id=song_ea8d6bc1b835a0f7)
- osong_bd629ec4886a6ae6 (song_id=song_4fe81fff18f14bf3)
- osong_4d5aab5c3cb37da0 (song_id=song_e551e0c0c7fac377)
- osong_f6fb9d27baadd69e (song_id=song_91e0bb2ffff44fc0)
- osong_41f6f0ecdf9f258f (song_id=song_8ed0cbde87d92616)

## Next step

- After a successful --apply, publish the RDB to S3 (see docs/firsthand-field-report-operations.md Step 3):
  `python3 master_db_s3_artifact.py publish --expect-remote-checksum <checksum from `status`>`
- Commit only data/firsthand_reports/*.json, the manifest, and this report — never the .sqlite file.
