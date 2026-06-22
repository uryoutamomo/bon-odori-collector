# Ph2 event occurrence dry-run apply

- generated_at: 2026-06-21T16:07:28.174145+00:00
- mode: DRY-RUN
- scope: copied_sqlite_only_no_notion_no_public_json
- target_db: `data/ph2_historical_reference_include_blocked_dry_run.sqlite`
- dry_run_db: `data/ph2_historical_reference_include_blocked_dry_run.sqlite`
- backup_db: ``
- db_committed: True
- rolled_back: False
- selected_count: 8
- applied_count: 8
- skipped_count: 6
- issues_count: 0
- issues_by_severity: {}
- dry_run_table_counts: {'event_occurrences': 214, 'occurrence_dates': 138, 'notion_sync_jobs': 10, 'ph2_event_occurrence_sync_jobs': 2}

## Applied

| event | action | before | after | inserted |
| --- | --- | --- | --- | --- |
| 濱町音頭盆踊り大会 | append_historical_reference_without_confirming_2026 |  to  / 浜町公園 |  to  / 浜町公園 | odate_ec21b005ddaa44f6 |
| 銀座一丁目東町会・新富町会 納涼盆踊り大会 | append_historical_reference_without_confirming_2026 |  to  /  |  to  /  | odate_69f8f21776f9a32c |
| ゐの市盆踊り～不忍夢～ | append_historical_reference_without_confirming_2026 |  to  / 上野恩賜公園 |  to  / 上野恩賜公園 | odate_d61d1ee01c66cad4 |
| 京橋盆踊り | append_historical_reference_without_confirming_2026 |  to  / 京橋エドグラン 京橋中央ひろば |  to  / 京橋エドグラン 京橋中央ひろば | odate_23599493a3ba4b16 |
| 新宿中央公園夏祭り 納涼盆踊り大会 | append_historical_reference_without_confirming_2026 |  to  / 新宿中央公園 ファンモアタイム広場 |  to  / 新宿中央公園 ファンモアタイム広場 | odate_7808c06b199324e2 |
| 森下二丁目盆踊り | append_historical_reference_without_confirming_2026 |  to  / 森下公園 |  to  / 森下公園 | odate_2cc909b7f2bf0b85 |
| 赤坂夏おどり（旧 赤坂盆踊り） | append_historical_reference_without_confirming_2026 |  to  / 赤坂サカス広場 |  to  / 赤坂サカス広場 | odate_2e11327e45ac481f |
| 都の辰巳深川 臨海ぼんおどり | append_historical_reference_without_confirming_2026 |  to  / 臨海小学校 |  to  / 臨海小学校 | odate_dfb92493810e50a0 |

## Skipped

- 品川区民まつり 品川第二地区: not_selected_mutation_type 
- 品川区民まつり 荏原第一地区: not_selected_mutation_type 
- 品川区民まつり 荏原第五地区: not_selected_mutation_type 
- 増上寺 地蔵尊盆踊り大会: not_selected_mutation_type 
- 旗岡八幡神社例大祭: not_selected_mutation_type 
- 盆☆Dance 夏休み最後の土曜は校庭で踊ろう！: not_selected_mutation_type 
