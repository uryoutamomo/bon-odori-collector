# Official notice report apply result

- generated_at: 2026-08-01T01:24:14.102396+00:00
- mode: apply
- resolved: True
- events_applied: 7
- events_unresolved: 0
- target_db: `data/bon_odori_master.sqlite`
- dry_run_db: ``
- backup_db: `data/backups/bon_odori_master.20260801T012414.102396+0000.sqlite.bak`
- db_committed: True
- rolled_back: False
- issues_by_severity: {}
- audit_issues_by_severity: {'medium': 1}

- evidence_id: `ev_4c8a6937e5e426a3`

## Applied events

- register_new occ_833412c94433491f (songs: 0; series_id: `series_293113a7c228a493`, series_created: True, venue_status: created)
- register_new occ_d761cd6a2e37d826 (songs: 0; series_id: `series_0821390013e0097f`, series_created: True, venue_status: created)
- register_new occ_8f33de55bc5484d1 (songs: 0; series_id: `series_2b0e80c4c8398277`, series_created: True, venue_status: created)
- register_new occ_87e5370ab1521e66 (songs: 0; series_id: `series_9ec4d7d31c58a66e`, series_created: True, venue_status: created)
- register_new occ_6da8ac3466c3051a (songs: 0; series_id: `series_f9330b5e5369c897`, series_created: True, venue_status: created)
- register_new occ_dbfeeb7ead962df0 (songs: 0; series_id: `series_0b95ee92bcc1a0fd`, series_created: True, venue_status: created)
- register_new occ_fb7e3ca703163fed (songs: 0; series_id: `series_86cd1e0c9f545a5e`, series_created: True, venue_status: created)

## Next step

- After a successful --apply, publish the RDB to S3 (see docs/official-notice-field-report-operations.md Step 3):
  `python3 master_db_s3_artifact.py publish --expect-remote-checksum <checksum from `status`>`
- If any events are unresolved, fix the report JSON (e.g. add an explicit occurrence_id) and re-run --apply;
  already-applied events are idempotent no-ops on re-run.
- Commit only data/official_notice_reports/*.json, the manifest, and this report — never the .sqlite file.
