# Official notice report apply result

- generated_at: 2026-08-12T07:32:12.758904+00:00
- mode: apply
- resolved: True
- events_applied: 9
- events_unresolved: 0
- target_db: `data/bon_odori_master.sqlite`
- dry_run_db: ``
- backup_db: `data/backups/bon_odori_master.20260812T073212.758904+0000.sqlite.bak`
- db_committed: True
- rolled_back: False
- issues_by_severity: {}
- audit_issues_by_severity: {}

- evidence_id: `ev_4dd2c7d6ec03e46e`

## Applied events

- register_new occ_be696a6eddc87312 (songs: 0; series_id: `series_1e9c1cc5f1669747`, series_created: True, venue_status: created)
- register_new occ_c8c19bd836c97d08 (songs: 0; series_id: `series_95e45ad2e43db1f3`, series_created: True, venue_status: created)
- register_new occ_2165bfd718be8378 (songs: 0; series_id: `series_501b0a7477437107`, series_created: True, venue_status: created)
- register_new occ_8b3890f083a577fa (songs: 0; series_id: `series_23613bb6b4ada0df`, series_created: True, venue_status: created)
- register_new occ_95e067e34d5e632c (songs: 0; series_id: `series_6a65eb23f2f48fbd`, series_created: True, venue_status: created)
- register_new occ_267aec464639de14 (songs: 0; series_id: `series_83c38f12a6e2693b`, series_created: True, venue_status: created)
- register_new occ_cf117f60531ba1c1 (songs: 0; series_id: `series_ce930fb670df5b97`, series_created: True, venue_status: created)
- register_new occ_d921b723d4531bc6 (songs: 0; series_id: `series_faae6fc7efd2528e`, series_created: True, venue_status: created)
- register_new occ_9b3ba0cd2a041649 (songs: 0; series_id: `series_b5c58ce70595183b`, series_created: True, venue_status: created)

## Out of scope (from report.skipped_events)

- 沼袋氷川神社（中野区）: 検知元記事の本文に沼袋氷川神社の盆踊りの記載がなく、載っているのは例大祭（2026年6月6日・7日）のみ。記事タイトルに『盆踊り』が含まれていたための誤検知。キューは『該当なし』が妥当。
- 練馬一丁目公園（練馬区）: 検知元記事で練馬一丁目公園に紐づく行事は『スイカ割り大会』であり盆踊りではない。同記事内の盆踊りは別会場の旭町小学校。キューは『該当なし』が妥当。旭町小学校は別途の会場候補になりうる。
- 氷川児童遊園（練馬区）: 盆踊り開催自体は区議の記事で確認できるが、正式な所在地も2026年の開催日も一次資料で裏取りできなかったため保留。
- 隅田公園 芝生広場（台東区）: 『隅田公園 七夕夜会』の盆踊りは実在するが開催日を裏取りできず保留。会場自体は ven_918cee224c6b19f7『隅田公園』として登録済み。

## Next step

- After a successful --apply, publish the RDB to S3 (see docs/official-notice-field-report-operations.md Step 3):
  `python3 master_db_s3_artifact.py publish --expect-remote-checksum <checksum from `status`>`
- If any events are unresolved, fix the report JSON (e.g. add an explicit occurrence_id) and re-run --apply;
  already-applied events are idempotent no-ops on re-run.
- Commit only data/official_notice_reports/*.json, the manifest, and this report — never the .sqlite file.
