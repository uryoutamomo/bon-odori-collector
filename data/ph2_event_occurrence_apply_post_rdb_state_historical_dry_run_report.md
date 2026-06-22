# Ph2 event occurrence dry-run apply

- generated_at: 2026-06-22T13:22:53.225953+00:00
- mode: DRY-RUN
- scope: copied_sqlite_only_no_notion_no_public_json
- target_db: `data/ph2_event_occurrence_apply_post_rdb_state_historical_dry_run.sqlite`
- dry_run_db: `data/ph2_event_occurrence_apply_post_rdb_state_historical_dry_run.sqlite`
- backup_db: ``
- db_committed: True
- rolled_back: False
- selected_count: 0
- applied_count: 0
- skipped_count: 11
- issues_count: 0
- issues_by_severity: {}
- dry_run_table_counts: {'event_occurrences': 222, 'occurrence_dates': 170, 'notion_sync_jobs': 10, 'ph2_event_occurrence_sync_jobs': 0}

## Applied

| event | action | before | after | inserted |
| --- | --- | --- | --- | --- |

## Skipped

- 濱町音頭盆踊り大会: already_applied
- 銀座一丁目東町会・新富町会 納涼盆踊り大会: already_applied
- ゐの市盆踊り～不忍夢～: already_applied
- 京橋盆踊り: already_applied
- 増上寺 地蔵尊盆踊り大会: not_selected_mutation_type
- 新宿中央公園夏祭り 納涼盆踊り大会: already_applied
- 旗岡八幡神社例大祭: not_selected_mutation_type
- 森下二丁目盆踊り: already_applied
- 盆☆Dance 夏休み最後の土曜は校庭で踊ろう！: not_selected_mutation_type
- 赤坂夏おどり（旧 赤坂盆踊り）: already_applied
- 都の辰巳深川 臨海ぼんおどり: already_applied
