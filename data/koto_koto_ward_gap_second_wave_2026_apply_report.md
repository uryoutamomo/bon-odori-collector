# Official notice report apply result

- generated_at: 2026-07-31T15:42:29.135753+00:00
- mode: apply
- resolved: True
- events_applied: 20
- events_unresolved: 0
- target_db: `data/bon_odori_master.sqlite`
- dry_run_db: ``
- backup_db: `data/backups/bon_odori_master.20260731T154229.135753+0000.sqlite.bak`
- db_committed: True
- rolled_back: False
- issues_by_severity: {}
- audit_issues_by_severity: {}

- evidence_id: `ev_4c881704f99e997d`

## Applied events

- register_new occ_67944b1715f8aaa4 (songs: 0; series_id: `series_138675a9108acc30`, series_created: True, venue_status: created)
- register_new occ_4fcc747c2d490ae4 (songs: 0; series_id: `series_8805551b56c57750`, series_created: True, venue_status: created)
- register_new occ_472f2827e41b676b (songs: 0; series_id: `series_bac5098ed8499aa5`, series_created: True, venue_status: created)
- register_new occ_4c6f06222bd906ac (songs: 0; series_id: `series_f073dad51e2a612e`, series_created: True, venue_status: created)
- register_new occ_9a6845c9eef189a2 (songs: 0; series_id: `series_be61292bb43f07ca`, series_created: True, venue_status: created)
- register_new occ_22f885022cdf1584 (songs: 0; series_id: `series_0ea1e65e2cac1624`, series_created: True, venue_status: created)
- register_new occ_e2b9ec2298ec4f32 (songs: 0; series_id: `series_36abaed7511bace4`, series_created: True, venue_status: created)
- register_new occ_fd1c503d3f6538d5 (songs: 0; series_id: `series_46dd6622b7a24183`, series_created: True, venue_status: created)
- register_new occ_251ebd5fe04d4d38 (songs: 0; series_id: `series_4cf0dd1854ebb9a4`, series_created: True, venue_status: created)
- register_new occ_12e9728c0a384d1b (songs: 0; series_id: `series_6cfb9e4fd5bc9291`, series_created: True, venue_status: created)
- register_new occ_cf0544b3561983b8 (songs: 0; series_id: `series_7481b2698085ef0b`, series_created: True, venue_status: created)
- register_new occ_5df32308eae3f789 (songs: 0; series_id: `series_8d27933790b4ff0a`, series_created: True, venue_status: created)
- register_new occ_c144b96d770e3b9e (songs: 0; series_id: `series_bcfa4fbdea67eb42`, series_created: True, venue_status: created)
- register_new occ_d4f2f14192a4ef64 (songs: 0; series_id: `series_4b403ea9d0f31beb`, series_created: True, venue_status: created)
- register_new occ_ef53e510c8842afb (songs: 0; series_id: `series_ad97cab2944e5330`, series_created: True, venue_status: reused)
- register_new occ_fbbf1f3dcb7ae7c3 (songs: 0; series_id: `series_30c44ed3c6bfcc52`, series_created: True, venue_status: created)
- register_new occ_64e9d25c0c48cc6b (songs: 0; series_id: `series_21c35b5027acafbb`, series_created: True, venue_status: created)
- register_new occ_b223cacd3b0c84eb (songs: 0; series_id: `series_634b8927954cef24`, series_created: True, venue_status: created)
- register_new occ_144344004e460a1a (songs: 0; series_id: `series_a5e73c6c264b42a1`, series_created: True, venue_status: created)
- register_new occ_4ed149af2fc84735 (songs: 0; series_id: `series_acc42959d06b0b8c`, series_created: True, venue_status: created)

## Out of scope (from report.skipped_events)

- 毛利町会 納涼こども花火まつり: 花火イベントで盆踊り実施の根拠なし。
- 砂町銀座 七夕まつり: 七夕・商店街イベントで盆踊り実施の根拠なし。
- 富岡八幡宮例祭（深川八幡祭り）: 神輿の水掛け祭りで盆踊り実施の根拠なし。
- 深川十五夜まつり: 十五夜イベントで盆踊り実施の根拠なし。

## Next step

- After a successful --apply, publish the RDB to S3 (see docs/official-notice-field-report-operations.md Step 3):
  `python3 master_db_s3_artifact.py publish --expect-remote-checksum <checksum from `status`>`
- If any events are unresolved, fix the report JSON (e.g. add an explicit occurrence_id) and re-run --apply;
  already-applied events are idempotent no-ops on re-run.
- Commit only data/official_notice_reports/*.json, the manifest, and this report — never the .sqlite file.
