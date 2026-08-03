# Official notice report apply result

- generated_at: 2026-08-03T14:42:52.791991+00:00
- mode: apply
- resolved: True
- events_applied: 4
- events_unresolved: 0
- target_db: `data/bon_odori_master.sqlite`
- dry_run_db: ``
- backup_db: `data/backups/bon_odori_master.20260803T144252.791991+0000.sqlite.bak`
- db_committed: True
- rolled_back: False
- issues_by_severity: {}
- audit_issues_by_severity: {}

- evidence_id: `ev_1cbac5578ee3b766`

## Applied events

- register_new occ_a748cf862474971b (songs: 0; series_id: `series_246d180b3e771796`, series_created: True, venue_status: created)
- register_new occ_eaaff144ec744dd6 (songs: 0; series_id: `series_3fc45d6317c8bee7`, series_created: True, venue_status: created)
- register_new occ_a6a07e16b806b14c (songs: 0; series_id: `series_38f3f0382a8105af`, series_created: True, venue_status: created)
- register_new occ_5c0b8546b2496353 (songs: 0; series_id: `series_666ce9a284230fed`, series_created: True, venue_status: created)

## Next step

- After a successful --apply, publish the RDB to S3 (see docs/official-notice-field-report-operations.md Step 3):
  `python3 master_db_s3_artifact.py publish --expect-remote-checksum <checksum from `status`>`
- If any events are unresolved, fix the report JSON (e.g. add an explicit occurrence_id) and re-run --apply;
  already-applied events are idempotent no-ops on re-run.
- Commit only data/official_notice_reports/*.json, the manifest, and this report — never the .sqlite file.
