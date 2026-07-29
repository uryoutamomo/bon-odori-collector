# Official notice report apply result

- generated_at: 2026-07-29T04:23:49.033356+00:00
- mode: dry_run
- resolved: True
- events_applied: 1
- events_unresolved: 0
- target_db: `data/x_poster_second_wave_komazawa_2026_dry_run.sqlite`
- dry_run_db: `data/x_poster_second_wave_komazawa_2026_dry_run.sqlite`
- backup_db: ``
- db_committed: True
- rolled_back: False
- issues_by_severity: {}
- audit_issues_by_severity: {}

- evidence_id: `ev_90360a227b977431`

## Applied events

- rename_series_and_register_new occ_733c8c66a928edff (songs: 0)

## Next step

- After a successful --apply, publish the RDB to S3 (see docs/official-notice-field-report-operations.md Step 3):
  `python3 master_db_s3_artifact.py publish --expect-remote-checksum <checksum from `status`>`
- If any events are unresolved, fix the report JSON (e.g. add an explicit occurrence_id) and re-run --apply;
  already-applied events are idempotent no-ops on re-run.
- Commit only data/official_notice_reports/*.json, the manifest, and this report — never the .sqlite file.
