# Official notice report apply result

- generated_at: 2026-07-30T10:22:11.140483+00:00
- mode: dry_run
- resolved: True
- events_applied: 1
- events_unresolved: 0
- target_db: `data/x_poster_nakarokugo_noryokai_2026_dry_run.sqlite`
- dry_run_db: `data/x_poster_nakarokugo_noryokai_2026_dry_run.sqlite`
- backup_db: ``
- db_committed: True
- rolled_back: False
- issues_by_severity: {}
- audit_issues_by_severity: {}

- evidence_id: `ev_b8b204fe293afe44`

## Applied events

- register_new occ_17eabcbe2b6ba4ea (songs: 0; series_id: `series_62fc7a282c40f31b`, series_created: True, venue_status: created)

## Next step

- After a successful --apply, publish the RDB to S3 (see docs/official-notice-field-report-operations.md Step 3):
  `python3 master_db_s3_artifact.py publish --expect-remote-checksum <checksum from `status`>`
- If any events are unresolved, fix the report JSON (e.g. add an explicit occurrence_id) and re-run --apply;
  already-applied events are idempotent no-ops on re-run.
- Commit only data/official_notice_reports/*.json, the manifest, and this report — never the .sqlite file.
