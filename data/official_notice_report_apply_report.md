# Official notice report apply result

- generated_at: 2026-07-28T15:35:22.842378+00:00
- mode: apply
- resolved: True
- events_applied: 2
- events_unresolved: 0
- target_db: `data/bon_odori_master.sqlite`
- dry_run_db: ``
- backup_db: `data/backups/bon_odori_master.20260728T153522.842378+0000.sqlite.bak`
- db_committed: True
- rolled_back: False
- issues_by_severity: {}
- audit_issues_by_severity: {'medium': 1}

- evidence_id: `ev_ceb9317930c93efa`

## Applied events

- confirm_existing occ_018fc76d38dcd38f (songs: 0)
- confirm_existing occ_3fa70d14d361b2f3 (songs: 0)

## Out of scope (from report.skipped_events)

- 麻布十番納涼まつり（8月22日・23日 麻布十番商店街全域）: RDBの既存レコードは「麻布十番納涼盆踊り大会」（会場: 網代公園）で、広報の「麻布十番納涼まつり」（商店街全域）と同一イベントか判別できない。関連はありそうだが会場が異なるため、突き合わせを確認してから反映する。
- 芝浦二丁目商店会納涼盆踊り大会（7月18日・19日 船路橋児童遊園前）: RDBに2026年の開催回が無い。新規登録の候補だが、既に開催日を過ぎており今シーズンの公開価値が無いため、シリーズ・会場の整備とあわせて別途判断する。
- 謝恩納涼盆踊り大会（7月26日・27日 善光寺境内）: 同上。RDBに2026年の開催回が無く、開催日も過ぎている。
- 盆ダンスフェスティバル2026（7月26日 白金児童遊園）: 同上。RDBに2026年の開催回が無く、開催日も過ぎている。
- 四の橋夏まつり（8月1日・2日 時計台広場）: RDBに2026年の開催回が無い。開催は今週末で公開価値はあるが、盆踊りが行われるかが広報の記載からは判別できないため、確認してから新規登録するか判断する。
- 芝浦まつり（7月24日・25日 なぎさ通りお祭り広場）: RDBに2026年の開催回が無く、開催日も過ぎている。
- 第29回新橋こいち祭（7月23日・24日）: RDBに 2026-07-23〜24 で登録済み・confirmed。広報と一致しており変更不要。

## Next step

- After a successful --apply, publish the RDB to S3 (see docs/official-notice-field-report-operations.md Step 3):
  `python3 master_db_s3_artifact.py publish --expect-remote-checksum <checksum from `status`>`
- If any events are unresolved, fix the report JSON (e.g. add an explicit occurrence_id) and re-run --apply;
  already-applied events are idempotent no-ops on re-run.
- Commit only data/official_notice_reports/*.json, the manifest, and this report — never the .sqlite file.
