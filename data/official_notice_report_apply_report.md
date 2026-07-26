# Official notice report apply result

- generated_at: 2026-07-26T14:44:13.734872+00:00
- mode: apply
- resolved: True
- events_applied: 1
- events_unresolved: 0
- target_db: `data/bon_odori_master.sqlite`
- dry_run_db: ``
- backup_db: `data/backups/bon_odori_master.20260726T144413.734872+0000.sqlite.bak`
- db_committed: True
- rolled_back: False
- issues_by_severity: {}
- audit_issues_by_severity: {'medium': 1}

- evidence_id: `ev_1af061c5c205e1d7`

## Applied events

- register_new occ_267608981c4ee9bd (songs: 0)

## Out of scope (from report.skipped_events)

- 亀有銀座商店街納涼盆踊り大会（occ_1df0a276422a54b5）: 同一会場だが主催町会が異なる別イベント。既存レコードは2025年実績が8月31日で8月下旬開催のもの。今回のポスター（7月17-20日・亀有中央町会/亀有三和町会主催）を既存レコードの日付として書き込まない

## Next step

- After a successful --apply, publish the RDB to S3 (see docs/official-notice-field-report-operations.md Step 3):
  `python3 master_db_s3_artifact.py publish --expect-remote-checksum <checksum from `status`>`
- If any events are unresolved, fix the report JSON (e.g. add an explicit occurrence_id) and re-run --apply;
  already-applied events are idempotent no-ops on re-run.
- Commit only data/official_notice_reports/*.json, the manifest, and this report — never the .sqlite file.
