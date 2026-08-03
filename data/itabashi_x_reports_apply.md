# Official notice report apply result

- generated_at: 2026-08-03T15:44:51.671392+00:00
- mode: apply
- resolved: True
- events_applied: 3
- events_unresolved: 0
- target_db: `data/bon_odori_master.sqlite`
- dry_run_db: ``
- backup_db: `data/backups/bon_odori_master.20260803T154451.671392+0000.sqlite.bak`
- db_committed: True
- rolled_back: False
- issues_by_severity: {}
- audit_issues_by_severity: {}

- evidence_id: `ev_90e7daea68b4496c`

## Applied events

- register_new occ_8d8a4036f11c5874 (songs: 0; series_id: `series_58adc2001f54172a`, series_created: True, venue_status: created)
- register_new occ_fc74cc7f0868ba17 (songs: 0; series_id: `series_e2b53a04e8b2585b`, series_created: True, venue_status: created)
- register_new occ_c0077e9258ce2e98 (songs: 0; series_id: `series_90b68944c641d05e`, series_created: True, venue_status: created)

## Next step

- After a successful --apply, publish the RDB to S3 (see docs/official-notice-field-report-operations.md Step 3):
  `python3 master_db_s3_artifact.py publish --expect-remote-checksum <checksum from `status`>`
- If any events are unresolved, fix the report JSON (e.g. add an explicit occurrence_id) and re-run --apply;
  already-applied events are idempotent no-ops on re-run.
- Commit only data/official_notice_reports/*.json, the manifest, and this report — never the .sqlite file.
