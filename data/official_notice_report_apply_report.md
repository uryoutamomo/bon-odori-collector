# Official notice report apply result

- generated_at: 2026-08-03T14:28:34.955151+00:00
- mode: apply
- resolved: True
- events_applied: 5
- events_unresolved: 0
- target_db: `data/bon_odori_master.sqlite`
- dry_run_db: ``
- backup_db: `data/backups/bon_odori_master.20260803T142834.955151+0000.sqlite.bak`
- db_committed: True
- rolled_back: False
- issues_by_severity: {}
- audit_issues_by_severity: {}

- evidence_id: `ev_7f38fb1278a33e7c`

## Applied events

- register_new occ_19a7483ef6395dfb (songs: 0; series_id: `series_d54b932297444e06`, series_created: True, venue_status: created)
- register_new occ_b5da8301aae875f0 (songs: 0; series_id: `series_bccfd9d9a08b64ed`, series_created: True, venue_status: created)
- register_new occ_22bfe7f4f6dd54cb (songs: 0; series_id: `series_9771037530f84ec2`, series_created: True, venue_status: created)
- register_new occ_ee34fb3bfe68aad1 (songs: 0; series_id: `series_1cb17d5ce3dc2940`, series_created: True, venue_status: created)
- register_new occ_2ce79fad1bbb4348 (songs: 0; series_id: `series_8a1be62d95f59220`, series_created: True, venue_status: created)

## Next step

- After a successful --apply, publish the RDB to S3 (see docs/official-notice-field-report-operations.md Step 3):
  `python3 master_db_s3_artifact.py publish --expect-remote-checksum <checksum from `status`>`
- If any events are unresolved, fix the report JSON (e.g. add an explicit occurrence_id) and re-run --apply;
  already-applied events are idempotent no-ops on re-run.
- Commit only data/official_notice_reports/*.json, the manifest, and this report — never the .sqlite file.
