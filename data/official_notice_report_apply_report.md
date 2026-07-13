# Official notice report apply result

- generated_at: 2026-07-13T02:38:53.548040+00:00
- mode: dry_run
- resolved: True
- events_applied: 4
- events_unresolved: 0
- target_db: `data/official_notice_report_apply_dry_run.sqlite`
- dry_run_db: `data/official_notice_report_apply_dry_run.sqlite`
- backup_db: ``
- db_committed: True
- rolled_back: False
- issues_by_severity: {}
- audit_issues_by_severity: {'medium': 1}

- evidence_id: `ev_0d7adba27171dbef`

## Applied events

- confirm_existing occ_225f239652267ed9 (songs: 0)
- confirm_existing occ_69eb62d9b1773ad9 (songs: 0)
- register_new occ_c97f48d221c7154f (songs: 0)
- confirm_existing occ_56e51b72ec7acc7e (songs: 0)

## Out of scope (from report.skipped_events)

- 湊三丁目町会 納涼子ども会: 盆踊り判定保留
- 湊二丁目町会 湊二お楽しみ会: 盆踊り判定保留
- 入船一・二丁目町会: 2027年3月開催予定、時期・内容とも対象外

## Next step

- After a successful --apply, publish the RDB to S3 (see docs/official-notice-field-report-operations.md Step 3):
  `python3 master_db_s3_artifact.py publish --expect-remote-checksum <checksum from `status`>`
- If any events are unresolved, fix the report JSON (e.g. add an explicit occurrence_id) and re-run --apply;
  already-applied events are idempotent no-ops on re-run.
- Commit only data/official_notice_reports/*.json, the manifest, and this report — never the .sqlite file.
