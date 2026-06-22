# Ph2 event occurrence dry-run apply

- generated_at: 2026-06-21T07:27:51.477068+00:00
- mode: DRY-RUN
- scope: copied_sqlite_only_no_notion_no_public_json
- target_db: `data/ph2_shinagawa_second_apply_dry_run.sqlite`
- dry_run_db: `data/ph2_shinagawa_second_apply_dry_run.sqlite`
- backup_db: ``
- db_committed: True
- rolled_back: False
- selected_count: 1
- applied_count: 1
- skipped_count: 13
- issues_count: 0
- issues_by_severity: {}
- dry_run_table_counts: {'event_occurrences': 214, 'occurrence_dates': 129, 'notion_sync_jobs': 9, 'ph2_event_occurrence_sync_jobs': 2}

## Applied

| event | before | after | notion job |
| --- | --- | --- | --- |
| 品川区民まつり 品川第二地区 |  to  / 城南小学校 | 2026-07-25 to 2026-07-26 / 天妙国寺 | nsj_054ac71c5ec10d2b |

## Skipped

- 濱町音頭盆踊り大会: not_current_official_mutation 
- 銀座一丁目東町会・新富町会 納涼盆踊り大会: not_current_official_mutation 
- ゐの市盆踊り～不忍夢～: not_current_official_mutation 
- 京橋盆踊り: not_current_official_mutation 
- 品川区民まつり 荏原第一地区: event_filter 
- 品川区民まつり 荏原第五地区: event_filter 
- 増上寺 地蔵尊盆踊り大会: not_current_official_mutation 
- 新宿中央公園夏祭り 納涼盆踊り大会: not_current_official_mutation 
- 旗岡八幡神社例大祭: not_current_official_mutation 
- 森下二丁目盆踊り: not_current_official_mutation 
- 盆☆Dance 夏休み最後の土曜は校庭で踊ろう！: not_current_official_mutation 
- 赤坂夏おどり（旧 赤坂盆踊り）: not_current_official_mutation 
- 都の辰巳深川 臨海ぼんおどり: not_current_official_mutation 
