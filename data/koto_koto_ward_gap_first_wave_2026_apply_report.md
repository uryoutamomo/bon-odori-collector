# Official notice report apply result

- generated_at: 2026-07-31T15:10:28.444251+00:00
- mode: apply
- resolved: True
- events_applied: 10
- events_unresolved: 0
- target_db: `data/bon_odori_master.sqlite`
- dry_run_db: ``
- backup_db: `data/backups/bon_odori_master.20260731T151028.444251+0000.sqlite.bak`
- db_committed: True
- rolled_back: False
- issues_by_severity: {}
- audit_issues_by_severity: {}

- evidence_id: `ev_e3d38a20682c7569`

## Applied events

- register_new occ_0974206b2ae82a0b (songs: 0; series_id: `series_11191b3b8c50f46e`, series_created: True, venue_status: created)
- register_new occ_60263287316bed4b (songs: 0; series_id: `series_1ea32e75f6407cf4`, series_created: True, venue_status: created)
- register_new occ_b3435b04a5d2db71 (songs: 0; series_id: `series_8ed431a7bb808e1e`, series_created: True, venue_status: created)
- register_new occ_02a3dc6a09e2d814 (songs: 0; series_id: `series_6b7e474e8f3f3d62`, series_created: True, venue_status: created)
- register_new occ_5f9b773629da1c5d (songs: 0; series_id: `series_49d65583de396d88`, series_created: True, venue_status: created)
- register_new occ_aadae78e07c0abb5 (songs: 0; series_id: `series_660cf37e17e106e7`, series_created: True, venue_status: created)
- register_new occ_4885af7bf56b6a66 (songs: 0; series_id: `series_bbf5e43ab2173d1c`, series_created: True, venue_status: created)
- register_new occ_d954ecefe2bb33de (songs: 0; series_id: `series_41d595db75f3fa04`, series_created: True, venue_status: created)
- register_new occ_e786a7e62b477081 (songs: 0; series_id: `series_cdf7a64fc8118019`, series_created: True, venue_status: created)
- register_new occ_0161f4cb8caa2afc (songs: 0; series_id: `series_c2f5e932f93fc8a4`, series_created: True, venue_status: created)

## Next step

- After a successful --apply, publish the RDB to S3 (see docs/official-notice-field-report-operations.md Step 3):
  `python3 master_db_s3_artifact.py publish --expect-remote-checksum <checksum from `status`>`
- If any events are unresolved, fix the report JSON (e.g. add an explicit occurrence_id) and re-run --apply;
  already-applied events are idempotent no-ops on re-run.
- Commit only data/official_notice_reports/*.json, the manifest, and this report — never the .sqlite file.
