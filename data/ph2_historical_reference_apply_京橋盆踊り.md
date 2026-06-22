# Ph2 event occurrence dry-run apply

- generated_at: 2026-06-21T16:14:36.988561+00:00
- mode: APPLY
- scope: source_master_db_apply_no_notion_no_public_json
- target_db: `data/bon_odori_master.sqlite`
- dry_run_db: ``
- backup_db: `data/backups/bon_odori_master.20260621T161436.988561+0000.sqlite.bak`
- db_committed: True
- rolled_back: False
- selected_count: 1
- applied_count: 1
- skipped_count: 13
- issues_count: 0
- issues_by_severity: {}
- dry_run_table_counts: {'event_occurrences': 214, 'occurrence_dates': 133, 'notion_sync_jobs': 10, 'ph2_event_occurrence_sync_jobs': 2}

## Applied

| event | action | before | after | inserted |
| --- | --- | --- | --- | --- |
| 京橋盆踊り | append_historical_reference_without_confirming_2026 |  to  / 京橋エドグラン 京橋中央ひろば |  to  / 京橋エドグラン 京橋中央ひろば | odate_23599493a3ba4b16 |

## Skipped

- 濱町音頭盆踊り大会: event_filter 
- 銀座一丁目東町会・新富町会 納涼盆踊り大会: event_filter 
- ゐの市盆踊り～不忍夢～: event_filter 
- 品川区民まつり 品川第二地区: not_selected_mutation_type 
- 品川区民まつり 荏原第一地区: not_selected_mutation_type 
- 品川区民まつり 荏原第五地区: not_selected_mutation_type 
- 増上寺 地蔵尊盆踊り大会: not_selected_mutation_type 
- 新宿中央公園夏祭り 納涼盆踊り大会: event_filter 
- 旗岡八幡神社例大祭: not_selected_mutation_type 
- 森下二丁目盆踊り: event_filter 
- 盆☆Dance 夏休み最後の土曜は校庭で踊ろう！: not_selected_mutation_type 
- 赤坂夏おどり（旧 赤坂盆踊り）: event_filter 
- 都の辰巳深川 臨海ぼんおどり: event_filter 
