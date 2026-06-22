# Ph2 event occurrence dry-run apply

- generated_at: 2026-06-21T03:15:58.019643+00:00
- mode: APPLY
- scope: source_master_db_apply_no_notion_no_public_json
- target_db: `/private/tmp/ph2_apply_guard_test.sqlite`
- dry_run_db: ``
- selected_count: 1
- applied_count: 1
- skipped_count: 13
- issues_count: 0
- issues_by_severity: {}
- dry_run_table_counts: {'event_occurrences': 214, 'occurrence_dates': 128, 'notion_sync_jobs': 8, 'ph2_event_occurrence_sync_jobs': 1}

## Applied

| event | before | after | notion job |
| --- | --- | --- | --- |
| 品川区民まつり 荏原第一地区 |  to  / 小山台小学校 | 2026-10-10 to  / 小山台小学校 | nsj_9f1e9140663ba631 |

## Skipped

- 濱町音頭盆踊り大会: not_current_official_mutation
- 銀座一丁目東町会・新富町会 納涼盆踊り大会: not_current_official_mutation
- ゐの市盆踊り～不忍夢～: not_current_official_mutation
- 京橋盆踊り: not_current_official_mutation
- 品川区民まつり 品川第二地区: event_filter
- 品川区民まつり 荏原第五地区: event_filter
- 増上寺 地蔵尊盆踊り大会: not_current_official_mutation
- 新宿中央公園夏祭り 納涼盆踊り大会: not_current_official_mutation
- 旗岡八幡神社例大祭: not_current_official_mutation
- 森下二丁目盆踊り: not_current_official_mutation
- 盆☆Dance 夏休み最後の土曜は校庭で踊ろう！: not_current_official_mutation
- 赤坂夏おどり（旧 赤坂盆踊り）: not_current_official_mutation
- 都の辰巳深川 臨海ぼんおどり: not_current_official_mutation
