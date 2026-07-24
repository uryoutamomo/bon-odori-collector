# Song probability year-over-year inheritance report

- generated_at: 2026-07-24T08:54:08.459699+00:00
- mode: apply
- target_year: 2026
- target_db: `data/bon_odori_master.sqlite`
- backup_db: `data/backups/bon_odori_master.20260724T085408.459699+0000.sqlite.bak`
- db_committed: True
- rolled_back: False

## Summary

- candidates_considered: 100
- rows_created: 100
- rows_skipped_no_evidence: 0
- probability_min: 48
- probability_max: 71
- issues_by_severity: {}
- audit_issues_by_severity: {'medium': 1}
- table_counts: {'event_investigation_tasks': 79, 'event_occurrences': 252, 'event_series': 241, 'evidence_items': 31183, 'external_record_links': 2654, 'historical_promotion_candidates': 16, 'master_meta': 0, 'notion_sync_jobs': 0, 'observed_occurrence_songs': 30772, 'observed_occurrences': 2164, 'occurrence_dates': 294, 'occurrence_evidence_links': 100, 'occurrence_song_evidence_links': 863, 'occurrence_songs': 705, 'predicted_occurrence_dates': 14, 'review_inbox_items': 0, 'schema_migrations': 1, 'song_aliases': 141, 'songs': 339, 'venue_aliases': 290, 'venues': 241, 'write_batches': 0}

## Scope

- Only series with BOTH a target_year occurrence and an earlier occurrence are considered.
- Only the single most recent past year per series is used as the inheritance source.
- A song already present on the target occurrence (any role) is never overwritten -- direct evidence always wins over inheritance.
- New rows are written with role='prediction', origin='inherited_prediction', inherited_from_year=<source year>.

## Sample created rows

- 盆ギリ恋歌: 70% (2025年実測, speakers=2)
- 赤坂音頭: 57% (2025年実測, speakers=1)
- 赤坂豊川音頭: 57% (2025年実測, speakers=1)
- かがやき音頭: 57% (2025年実測, speakers=1)
- ドダレバチ: 57% (2025年実測, speakers=1)
- 白浜音頭: 57% (2025年実測, speakers=1)
- 佐渡おけさ: 57% (2025年実測, speakers=1)
- 郡上節かわさき: 57% (2025年実測, speakers=1)
- 炭坑節: 57% (2025年実測, speakers=1)
- ステテコシャンシャン: 57% (2025年実測, speakers=1)
- ニッポンワッショイ: 57% (2025年実測, speakers=1)
- 東京音頭: 57% (2025年実測, speakers=1)
- Hey Mr 恵比寿: 57% (2025年実測, speakers=1)
- YES YES EBISU: 57% (2025年実測, speakers=1)
- YES YES YBISU: 57% (2025年実測, speakers=1)
- おてもやん: 60% (2025年実測, speakers=1)
- 八木節: 57% (2025年実測, speakers=1)
- 大東京音頭: 57% (2025年実測, speakers=1)
- 能登島さし音頭: 57% (2025年実測, speakers=1)
- 渋谷で盆ジョヴィ 2025 ダンシングヒーロー: 57% (2025年実測, speakers=1)
