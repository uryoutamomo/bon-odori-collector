# Ph2 event occurrence apply plan

- generated_at: 2026-06-21T07:27:05.010351+00:00
- mutation_count: 14
- mutations_by_type: {'append_historical_reference_without_confirming_2026': 8, 'update_existing_2026_occurrence_from_current_official_source': 3, 'keep_investigation_queue': 3}
- blocked_or_review_required_count: 13
- predicted_date_job_count: 10
- predicted_date_jobs_by_application_status: {'candidate_for_2026_occurrence': 6, 'candidate_for_existing_2026_occurrence': 1, 'matches_curated': 1, 'superseded_by_curated': 2}

## Current Official 2026 Mutations

| event | current | proposed | venue | flags | apply |
| --- | --- | --- | --- | --- | --- |
| 品川区民まつり 品川第二地区 |  / 城南小学校 | 2026-07-25 to 2026-07-26 | 天妙国寺境内 (exact_match) |  | ready_after_dual_write |
| 品川区民まつり 荏原第一地区 | 2026-10-10 / 小山台小学校 | 2026-10-10 | 小山台小学校 (ambiguous_match; suggestion: 小山台小学校 1.0) | target_already_has_date, venue_lookup_ambiguous_match | blocked |
| 品川区民まつり 荏原第五地区 |  / 旧杜松小学校 | 2026-07-18 to 2026-07-19 | 杜松ホーム (missing_in_master) | venue_change, venue_lookup_missing_in_master, human_review_required | blocked |

## Historical Reference Mutations

| event | historical date | venue | confidence | flags |
| --- | --- | --- | --- | --- |
| 濱町音頭盆踊り大会 | 2025-09-27 | 浜町公園中央広場 (missing_in_master; suggestion: 浜町公園 0.92) | medium | historical_venue_lookup_missing_in_master, human_review_required |
| 銀座一丁目東町会・新富町会 納涼盆踊り大会 | 2025-07-19 | 京橋プラザ (missing_in_master) | medium | historical_venue_lookup_missing_in_master, human_review_required |
| ゐの市盆踊り～不忍夢～ | 2025-08-09 to 2025-08-11 | 上野恩賜公園 (ambiguous_match; suggestion: 上野恩賜公園 1.0) | medium | historical_venue_lookup_ambiguous_match, human_review_required |
| 京橋盆踊り | 2025-08-29 to 2025-08-30 | 京橋中央ひろば（ガレリア） (missing_in_master; suggestion: 京橋エドグラン 京橋中央ひろば 0.56) | high | historical_venue_lookup_missing_in_master |
| 新宿中央公園夏祭り 納涼盆踊り大会 | 2025-08-23 to 2025-08-24 | 新宿中央公園 ファンモアタイムひろば (missing_in_master; suggestion: 新宿中央公園 ファンモアタイム広場 0.848) | medium | historical_venue_lookup_missing_in_master, human_review_required |
| 森下二丁目盆踊り | 2025-07-19 to 2025-07-20 | 森下公園 (ambiguous_match; suggestion: 森下公園 1.0) | medium | historical_venue_lookup_ambiguous_match, human_review_required |
| 赤坂夏おどり（旧 赤坂盆踊り） | 2025-08-29 to 2025-08-30 | TBS赤坂サカス広場 (missing_in_master; suggestion: 赤坂サカス広場 0.92) | medium | historical_venue_lookup_missing_in_master, human_review_required |
| 都の辰巳深川 臨海ぼんおどり | 2025-07-19 | 臨海小学校校庭 (missing_in_master; suggestion: 臨海小学校 0.92) | medium | historical_venue_lookup_missing_in_master, human_review_required |

## Keep In Queue

| event | action | note |
| --- | --- | --- |
| 増上寺 地蔵尊盆踊り大会 | keep_as_date_research_task | Official annual page confirms the event name but not a usable current-year date. |
| 旗岡八幡神社例大祭 | keep_as_date_research_task | Homepage did not expose a usable 2026 date or bon-odori row in the previous pass. |
| 盆☆Dance 夏休み最後の土曜は校庭で踊ろう！ | source_specific_follow_up | Index/map source needs a specific row follow-up. |

## Predicted Date Jobs

| event | predicted | basis | status | notion job |
| --- | --- | --- | --- | --- |
| シタマチ.ふるさと盆踊り大会 | 2026-08-15 | 8月第3土曜 | candidate_for_2026_occurrence | pending |
| 丸の内de盆踊り | 2026-07-31 | 7月の最終金曜 | candidate_for_2026_occurrence | pending |
| 歌舞伎町BON ODORI | 2026-08-15 | 8月第3土曜 | candidate_for_2026_occurrence | pending |
| 第28回新橋こいち祭 盆踊り | 2026-07-23 | 7月第4木曜 | candidate_for_2026_occurrence | pending |
| 自由が丘納涼盆踊り大会 | 2026-07-18 to 2026-07-20 | 7月16日前後の土曜 | candidate_for_2026_occurrence | pending |
| 西久保八幡神社 盆踊り | 2026-08-08 | 8月9日前後の週末 | candidate_for_2026_occurrence | pending |
| 謝恩納涼盆踊り大会（青山善光寺） | 2026-07-27 | 7月の最終月曜 | candidate_for_existing_2026_occurrence | pending |
| 山王音頭と民踊大会 | 2026-06-13 to 2026-06-15 | 毎年6/13開始 | matches_curated |  |
| みたままつり 納涼民踊のつどい | 2026-07-14 to 2026-07-16 | 7月14日前後 | superseded_by_curated |  |
| 郡上おどり in 青山 | 2026-06-19 | 6月17日前後の金曜 | superseded_by_curated |  |

## Write Order

- 1. Apply current official 2026 updates only after dual-write code exists and review flags are resolved.
- 2. Append historical references as evidence notes; do not alter 2026 confirmed dates.
- 3. Keep predicted dates as candidate/review jobs unless promoted by official current-year evidence.
- 4. Regenerate local public JSON dry-run and compare collector/site before any deploy.
