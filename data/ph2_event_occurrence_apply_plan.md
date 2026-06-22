# Ph2 event occurrence apply plan

- generated_at: 2026-06-22T13:57:57.969166+00:00
- mutation_count: 12
- mutations_by_type: {'append_historical_reference_without_confirming_2026': 8, 'update_existing_2026_occurrence_from_current_official_source': 1, 'keep_investigation_queue': 3}
- blocked_or_review_required_count: 3
- already_applied_current_official_count: 1
- already_applied_historical_reference_count: 8
- predicted_date_job_count: 12
- predicted_date_jobs_by_application_status: {'candidate_for_2026_occurrence': 8, 'matches_curated': 1, 'superseded_by_curated': 3}

## Current Official 2026 Mutations

| event | current | proposed | venue | flags | apply |
| --- | --- | --- | --- | --- | --- |
| 品川区民まつり 荏原第五地区 | 2026-07-18 to 2026-07-19 / 杜松ホーム | 2026-07-18 to 2026-07-19 | 杜松ホーム (exact_match) |  | already_applied |

## Historical Reference Mutations

| event | historical date | venue | confidence | flags | apply |
| --- | --- | --- | --- | --- | --- |
| 濱町音頭盆踊り大会 | 2025-09-27 | 浜町公園中央広場 (missing_in_master; suggestion: 浜町公園 0.92) | medium |  | already_applied |
| 銀座一丁目東町会・新富町会 納涼盆踊り大会 | 2025-07-19 | 京橋プラザ (missing_in_master) | medium |  | already_applied |
| ゐの市盆踊り～不忍夢～ | 2025-08-09 to 2025-08-11 | 上野恩賜公園 (exact_match) | medium |  | already_applied |
| 京橋盆踊り | 2025-08-29 to 2025-08-30 | 京橋中央ひろば（ガレリア） (missing_in_master; suggestion: 京橋エドグラン 京橋中央ひろば 0.56) | high |  | already_applied |
| 新宿中央公園夏祭り 納涼盆踊り大会 | 2025-08-23 to 2025-08-24 | 新宿中央公園 ファンモアタイムひろば (missing_in_master; suggestion: 新宿中央公園 ファンモアタイム広場 0.848) | medium |  | already_applied |
| 森下二丁目盆踊り | 2025-07-19 to 2025-07-20 | 森下公園 (exact_match) | medium |  | already_applied |
| 赤坂夏おどり（旧 赤坂盆踊り） | 2025-08-29 to 2025-08-30 | TBS赤坂サカス広場 (missing_in_master; suggestion: 赤坂サカス広場 0.92) | medium |  | already_applied |
| 都の辰巳深川 臨海ぼんおどり | 2025-07-19 | 臨海小学校校庭 (missing_in_master; suggestion: 臨海小学校 0.92) | medium |  | already_applied |

## Keep In Queue

| event | action | note |
| --- | --- | --- |
| 増上寺 地蔵尊盆踊り大会 | keep_as_date_research_task | Official annual page was rechecked: it confirms the event name and directs inquiries to 安国殿, but still does not publish a usable 2026 date. |
| 旗岡八幡神社例大祭 | keep_as_date_research_task | Homepage was rechecked: latest visible festival news remains 令和7年/2025例大祭 material, with no usable 2026 date or bon-odori row. |
| 盆☆Dance 夏休み最後の土曜は校庭で踊ろう！ | source_specific_follow_up | Current 東京内外の盆踊りマップ upcoming-all page was rechecked and did not expose 盆☆Dance/横川小学校; keep as source-specific follow-up. |

## Predicted Date Jobs

| event | predicted | basis | status | notion job |
| --- | --- | --- | --- | --- |
| シタマチ.ふるさと盆踊り大会 | 2026-08-15 | 8月第3土曜 | candidate_for_2026_occurrence | pending |
| 丸の内de盆踊り | 2026-07-31 | 7月の最終金曜 | candidate_for_2026_occurrence | pending |
| 歌舞伎町BON ODORI | 2026-08-15 | 8月第3土曜 | candidate_for_2026_occurrence | pending |
| 第15回 鴨台盆踊り | 2026-07-04 to 2026-07-05 | 7月6日前後の週末 | candidate_for_2026_occurrence | pending |
| 自由が丘納涼盆踊り大会 | 2026-07-18 to 2026-07-20 | 7月16日前後の土曜 | candidate_for_2026_occurrence | pending |
| 西久保八幡神社 盆踊り | 2026-08-08 | 8月9日前後の週末 | candidate_for_2026_occurrence | pending |
| 謝恩納涼盆踊り大会（青山善光寺） | 2026-07-27 | 7月の最終月曜 | candidate_for_2026_occurrence | pending |
| 赤坂浄土寺盆踊り大会 | 2026-07-26 to 2026-07-27 | 7月26日前後 | candidate_for_2026_occurrence | pending |
| 山王音頭と民踊大会 | 2026-06-13 to 2026-06-15 | 毎年6/13開始 | matches_curated |  |
| みたままつり 納涼民踊のつどい | 2026-07-14 to 2026-07-16 | 7月14日前後 | superseded_by_curated |  |
| 第28回新橋こいち祭 盆踊り | 2026-07-23 | 7月第4木曜 | superseded_by_curated | superseded_by_curated |
| 郡上おどり in 青山 | 2026-06-19 | 6月17日前後の金曜 | superseded_by_curated | superseded_by_curated |

## Write Order

- 1. Apply current official 2026 updates through the reviewed RDB-primary path when review flags are resolved.
- 2. Append historical references as evidence notes; do not alter 2026 confirmed dates.
- 3. Keep predicted dates as candidate/review jobs unless promoted by official current-year evidence.
- 4. Regenerate local public JSON dry-run and compare collector/site before any deploy.
