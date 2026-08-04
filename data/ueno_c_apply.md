# Official notice report apply result

- generated_at: 2026-08-04T00:51:37.983835+00:00
- mode: apply
- resolved: True
- events_applied: 2
- events_unresolved: 0
- target_db: `data/bon_odori_master.sqlite`
- dry_run_db: ``
- backup_db: `data/backups/bon_odori_master.20260804T005137.983835+0000.sqlite.bak`
- db_committed: True
- rolled_back: False
- issues_by_severity: {}
- audit_issues_by_severity: {}

- evidence_id: `ev_c06e2ce3c5a62136`

## Applied events

- register_new occ_c269edeedf7a5b71 (songs: 0; series_id: `series_237003fb0cfa2577`, series_created: True, venue_status: reused)
- confirm_existing occ_0ee14ffbf15fd0cf (songs: 0)

## Next step

- After a successful --apply, publish the RDB to S3 (see docs/official-notice-field-report-operations.md Step 3):
  `python3 master_db_s3_artifact.py publish --expect-remote-checksum <checksum from `status`>`
- If any events are unresolved, fix the report JSON (e.g. add an explicit occurrence_id) and re-run --apply;
  already-applied events are idempotent no-ops on re-run.
- Commit only data/official_notice_reports/*.json, the manifest, and this report — never the .sqlite file.
