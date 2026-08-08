# Official notice report apply result

- generated_at: 2026-08-08T02:13:10.885023+00:00
- mode: apply
- resolved: True
- events_applied: 4
- events_unresolved: 0
- target_db: `data/bon_odori_master.sqlite`
- dry_run_db: ``
- backup_db: `data/backups/bon_odori_master.20260808T021310.885023+0000.sqlite.bak`
- db_committed: True
- rolled_back: False
- issues_by_severity: {}
- audit_issues_by_severity: {}

- evidence_id: `ev_9dcb2843c782fb3d`

## Applied events

- register_new occ_eaec6c8c64246bdd (songs: 0; series_id: `series_c227322c3ca620e0`, series_created: True, venue_status: created)
- register_new occ_6c73b39fde75ee48 (songs: 0; series_id: `series_0020eb7abb971952`, series_created: True, venue_status: created)
- register_new occ_e107e712299c6c98 (songs: 0; series_id: `series_ee434210627c7a1f`, series_created: True, venue_status: created)
- register_new occ_7dd5908e2fc8e6f7 (songs: 0; series_id: `series_e908b6142809a020`, series_created: True, venue_status: created)

## Next step

- After a successful --apply, publish the RDB to S3 (see docs/official-notice-field-report-operations.md Step 3):
  `python3 master_db_s3_artifact.py publish --expect-remote-checksum <checksum from `status`>`
- If any events are unresolved, fix the report JSON (e.g. add an explicit occurrence_id) and re-run --apply;
  already-applied events are idempotent no-ops on re-run.
- Commit only data/official_notice_reports/*.json, the manifest, and this report — never the .sqlite file.
