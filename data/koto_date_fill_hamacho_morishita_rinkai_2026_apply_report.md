# Official notice report apply result

- generated_at: 2026-07-31T14:51:19.803999+00:00
- mode: apply
- resolved: True
- events_applied: 3
- events_unresolved: 0
- target_db: `data/bon_odori_master.sqlite`
- dry_run_db: ``
- backup_db: `data/backups/bon_odori_master.20260731T145119.803999+0000.sqlite.bak`
- db_committed: True
- rolled_back: False
- issues_by_severity: {}
- audit_issues_by_severity: {}

- evidence_id: `ev_e6afdb858d5177fa`

## Applied events

- confirm_existing occ_1a4d1fa95a29cc39 (songs: 0)
- confirm_existing occ_69ee7abd5466f5fd (songs: 0)
- confirm_existing occ_56b5ccafaa074788 (songs: 0)

## Next step

- After a successful --apply, publish the RDB to S3 (see docs/official-notice-field-report-operations.md Step 3):
  `python3 master_db_s3_artifact.py publish --expect-remote-checksum <checksum from `status`>`
- If any events are unresolved, fix the report JSON (e.g. add an explicit occurrence_id) and re-run --apply;
  already-applied events are idempotent no-ops on re-run.
- Commit only data/official_notice_reports/*.json, the manifest, and this report — never the .sqlite file.
