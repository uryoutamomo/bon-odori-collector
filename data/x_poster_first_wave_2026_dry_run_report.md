# Official notice report apply result

- generated_at: 2026-07-29T02:57:55.686948+00:00
- mode: dry_run
- resolved: True
- events_applied: 11
- events_unresolved: 0
- target_db: `data/x_poster_first_wave_2026_dry_run.sqlite`
- dry_run_db: `data/x_poster_first_wave_2026_dry_run.sqlite`
- backup_db: ``
- db_committed: True
- rolled_back: False
- issues_by_severity: {}
- audit_issues_by_severity: {'medium': 1}

- evidence_id: `ev_38e8b7f24ef684b4`

## Applied events

- register_new occ_b4377cd29622435e (songs: 0)
- register_new occ_a18730b884f5ae1b (songs: 0)
- register_new occ_fc3fc0f450f1cd87 (songs: 0)
- register_new occ_959986858d839ecb (songs: 0)
- register_new occ_f4dc297759a67c23 (songs: 0)
- register_new occ_f0965eb6ed8e3bfd (songs: 0)
- register_new occ_6fa9afbb74d69020 (songs: 0)
- register_new occ_30e49e010d502f7c (songs: 0)
- register_new occ_c6e8eaa5b615b0f5 (songs: 0)
- register_new occ_9183bc6314ad617f (songs: 0)
- register_new occ_a6508616f6a41e4a (songs: 0)

## Out of scope (from report.skipped_events)

- 東四ツ木の盆踊り（名称推定）: 会場・固有名称が本文のみでは不明。画像を確認後に別レポートで扱う。
- 仲六郷一丁目町会 納涼会: 会場不明のため、register_newの必須会場を推測で補わない。
- 田園調布南町会の盆踊り: 会場不明のため、register_newの必須会場を推測で補わない。

## Next step

- After a successful --apply, publish the RDB to S3 (see docs/official-notice-field-report-operations.md Step 3):
  `python3 master_db_s3_artifact.py publish --expect-remote-checksum <checksum from `status`>`
- If any events are unresolved, fix the report JSON (e.g. add an explicit occurrence_id) and re-run --apply;
  already-applied events are idempotent no-ops on re-run.
- Commit only data/official_notice_reports/*.json, the manifest, and this report — never the .sqlite file.
