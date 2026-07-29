# Official notice report apply result

- generated_at: 2026-07-29T04:18:16.344169+00:00
- mode: dry_run
- resolved: True
- events_applied: 5
- events_unresolved: 0
- target_db: `data/x_poster_second_wave_remainder_2026_dry_run.sqlite`
- dry_run_db: `data/x_poster_second_wave_remainder_2026_dry_run.sqlite`
- backup_db: ``
- db_committed: True
- rolled_back: False
- issues_by_severity: {}
- audit_issues_by_severity: {}

- evidence_id: `ev_6a5254daed0d614b`

## Applied events

- register_new occ_bca17a749d5e5961 (songs: 0)
- register_new occ_8467bb981f7d8e0b (songs: 0)
- register_new occ_167d265928d2c047 (songs: 0)
- register_new occ_ea99cdf3d2069be4 (songs: 0)
- confirm_existing occ_ab85373caa464eca (songs: 0)

## Next step

- After a successful --apply, publish the RDB to S3 (see docs/official-notice-field-report-operations.md Step 3):
  `python3 master_db_s3_artifact.py publish --expect-remote-checksum <checksum from `status`>`
- If any events are unresolved, fix the report JSON (e.g. add an explicit occurrence_id) and re-run --apply;
  already-applied events are idempotent no-ops on re-run.
- Commit only data/official_notice_reports/*.json, the manifest, and this report — never the .sqlite file.
