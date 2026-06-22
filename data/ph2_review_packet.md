# Ph2 review packet

- generated_at: 2026-06-22T01:22:49.528009+00:00
- scope: local_review_packet_no_writes

## Review Order

- changed_file_count: 117
- bucket_counts: {'A_scripts_review': 1, 'B_ph2_review_reports': 18, 'C_review_queue_evidence': 7, 'D_generated_master_rdb_artifacts': 12, 'E_public_export_dry_run_artifacts': 4, 'F_public_output_modified_do_not_wholesale_deploy': 5, 'G_youtube_song_master_side_changes': 3, 'H_repo_housekeeping': 1, 'Z_other': 66}

### A_scripts_review

- `?? audit_master_rdb.py`

### B_ph2_review_reports

- ` M data/ph2_cutover_readiness.json`
- ` M data/ph2_cutover_readiness.md`
- `?? data/ph2_event_occurrence_apply_plan.json`
- `?? data/ph2_event_occurrence_apply_plan.md`
- `?? data/ph2_review_packet.json`
- `?? data/ph2_review_packet.md`
- `?? data/pre_cutover_p0_apply_plan.json`
- `?? data/pre_cutover_p0_apply_plan.md`
- `?? data/public_events_diff_classification.json`
- `?? data/public_events_diff_classification.md`
- `?? data/public_events_sync_guard.json`
- `?? data/public_events_sync_guard.md`
- `?? data/public_individual_review_priority.json`
- `?? data/public_individual_review_priority.md`
- `?? data/public_restore_candidate_breakdown.json`
- `?? data/public_restore_candidate_breakdown.md`
- `?? data/song_occurrence_collapse_analysis.json`
- `?? data/song_occurrence_collapse_analysis.md`

### C_review_queue_evidence

- `A  data/historical_promotion_candidates.json`
- `A  data/historical_promotion_candidates.md`
- `A  data/observed_promotion_candidates.json`
- `A  data/observed_promotion_candidates.md`
- `A  data/registered_event_investigation_queue.json`
- `A  data/registered_event_investigation_queue.md`
- `?? data/pre_cutover_p0_research.md`

### F_public_output_modified_do_not_wholesale_deploy

- ` M data/public/event_songs_public.json`
- ` M data/public/events_public.js`
- ` M data/public/events_public.json`
- ` M data/public/venues_geo.json`
- ` M data/public/venues_public.json`

### G_youtube_song_master_side_changes

- ` M build_youtube_song_master.py`
- ` M data/youtube_song_master.json`
- ` M data/youtube_song_master_review.md`

### D_generated_master_rdb_artifacts

- `?? data/master_rdb_event_song_occurrences_public.dry_run.json`
- `?? data/master_rdb_event_song_occurrences_public.production_preview.json`
- `?? data/master_rdb_ph1_freeze_release_proposal.json`
- `?? data/master_rdb_ph1_freeze_release_proposal.md`
- `?? data/master_rdb_public_dry_run/event_songs_public.json`
- `?? data/master_rdb_public_dry_run/events_public.js`
- `?? data/master_rdb_public_dry_run/events_public.json`
- `?? data/master_rdb_public_dry_run/public_date_prediction_apply_result.json`
- `?? data/master_rdb_public_production_preview/event_songs_public.json`
- `?? data/master_rdb_public_production_preview/events_public.js`
- `?? data/master_rdb_public_production_preview/events_public.json`
- `?? data/master_rdb_public_production_preview/public_date_prediction_apply_result.json`

### E_public_export_dry_run_artifacts

- `?? data/current_public_dry_run/event_songs_public.json`
- `?? data/current_public_dry_run/events_public.js`
- `?? data/current_public_dry_run/events_public.json`
- `?? data/current_public_dry_run/public_date_prediction_apply_result.json`

### H_repo_housekeeping

- ` M .gitignore`

## Venue Review

- row_count: 11
- by_decision_bucket: {'alias_candidate': 3, 'new_or_missing_venue_review': 1, 'possible_alias_review': 2, 'same_venue_confirmed': 5}

| decision | event | purpose | proposed | current | suggestion | flags |
| --- | --- | --- | --- | --- | --- | --- |
| alias_candidate | 濱町音頭盆踊り大会 | historical_reference_only | 浜町公園中央広場 | 浜町公園 | 浜町公園 (0.92) |  |
| alias_candidate | 赤坂夏おどり（旧 赤坂盆踊り） | historical_reference_only | TBS赤坂サカス広場 | 赤坂サカス広場 | 赤坂サカス広場 (0.92) |  |
| alias_candidate | 都の辰巳深川 臨海ぼんおどり | historical_reference_only | 臨海小学校校庭 | 臨海小学校 | 臨海小学校 (0.92) |  |
| new_or_missing_venue_review | 銀座一丁目東町会・新富町会 納涼盆踊り大会 | historical_reference_only | 京橋プラザ |  |  |  |
| possible_alias_review | 京橋盆踊り | historical_reference_only | 京橋中央ひろば（ガレリア） | 京橋エドグラン 京橋中央ひろば | 京橋エドグラン 京橋中央ひろば (0.56) |  |
| possible_alias_review | 新宿中央公園夏祭り 納涼盆踊り大会 | historical_reference_only | 新宿中央公園 ファンモアタイムひろば | 新宿中央公園 ファンモアタイム広場 | 新宿中央公園 ファンモアタイム広場 (0.848) |  |
| same_venue_confirmed | 品川区民まつり 品川第二地区 | current_2026_official_update | 天妙国寺境内 | 天妙国寺 |  |  |
| same_venue_confirmed | 品川区民まつり 荏原第一地区 | current_2026_official_update | 小山台小学校 | 小山台小学校 |  |  |
| same_venue_confirmed | 品川区民まつり 荏原第五地区 | current_2026_official_update | 杜松ホーム | 杜松ホーム |  |  |
| same_venue_confirmed | ゐの市盆踊り～不忍夢～ | historical_reference_only | 上野恩賜公園 | 上野恩賜公園 |  |  |
| same_venue_confirmed | 森下二丁目盆踊り | historical_reference_only | 森下公園 | 森下公園 |  |  |

## Public Diff Review

- event_counts_match: True
- collector_only_count: 0
- site_only_count: 0
- common_rows_with_diff: 0
- high_risk_diff_counts: {}

Suggested handling:
- historical_reference: classify before any site wholesale sync
- historical_slide: classify before any site wholesale sync
- season_hint: classify before any site wholesale sync
- date_prediction: review individually; only 2 examples currently
- detail: review individually; only 2 examples currently

## Classified Public Diff Actions

- high_risk_event_count: 0
- high_risk_diff_record_count: 0
- records_by_family: {}
- records_by_action: {}
- events_by_action: {}

### Field-Level Site Update Candidates

| event | venue | field |
| --- | --- | --- |
| none |  |  |

### Restore or Export Postprocess Examples

| event | venue | families | fields |
| --- | --- | --- | ---: |

### Individual Review Examples

| event | venue | families | fields |
| --- | --- | --- | ---: |

## Public Restore Candidate Breakdown

- candidate_event_count: 76
- postprocess_exact_count: 76
- collector_restore_or_manual_review_count: 0
- by_resolution: {'regenerate_exact_via_historical_reference_postprocess': 18, 'regenerate_exact_via_season_hint_postprocess': 58}

| event | venue | resolution | fields |
| --- | --- | --- | ---: |
| -両国- 江戸NOREN 妖怪BON DANCE | -両国-江戸NOREN | regenerate_exact_via_historical_reference_postprocess | 7 |
| GMOシブヤエンタメ祭 × JAME盆踊り | 宮下公園 | regenerate_exact_via_historical_reference_postprocess | 7 |
| SHIBUYA MIYASHITA PARK BON DANCE | 宮下公園 | regenerate_exact_via_season_hint_postprocess | 5 |
| Tokyo江戸ウィーク～下町盆踊りフェス～ | 上野恩賜公園 | regenerate_exact_via_season_hint_postprocess | 5 |
| しながわ運河まつり ステージプログラム | 東品川海上公園 | regenerate_exact_via_season_hint_postprocess | 5 |
| すみだ公園の盆踊り（名称推定） | すみだ公園（隅田公園・墨田区側） | regenerate_exact_via_season_hint_postprocess | 5 |
| ゐの市盆踊り～不忍夢～ | 上野恩賜公園 | regenerate_exact_via_season_hint_postprocess | 5 |
| アークヒルズ秋祭り 盆踊り | アーク・カラヤン広場（アークヒルズ） | regenerate_exact_via_season_hint_postprocess | 5 |
| アースデイ東京2025 イマジン盆踊り部 | 代々木公園野外ステージ | regenerate_exact_via_historical_reference_postprocess | 7 |
| イベント名未確認（晴海ふ頭公園） | 晴海ふ頭公園 | regenerate_exact_via_historical_reference_postprocess | 7 |
| イベント名未確認（築地社会教育会館） | 築地社会教育会館 | regenerate_exact_via_season_hint_postprocess | 5 |
| シタマチ.ふるさと盆踊り大会 | おかちまちパンダ広場（御徒町駅南口駅前広場） | regenerate_exact_via_historical_reference_postprocess | 7 |
| 上笄町会お祭り 盆踊り | 長谷寺（西麻布・麻布大観音） | regenerate_exact_via_season_hint_postprocess | 5 |
| 上野盆踊り会（厚澄会） | 上野恩賜公園 | regenerate_exact_via_season_hint_postprocess | 5 |
| 中之郷公園の盆踊り（名称推定） | 中之郷公園（中之郷児童遊園） | regenerate_exact_via_season_hint_postprocess | 5 |
| 中原共和町会 戸越八幡神社祭礼 盆踊り | 平塚中央公園 | regenerate_exact_via_season_hint_postprocess | 5 |
| 丸の内de盆踊り | 行幸通り | regenerate_exact_via_historical_reference_postprocess | 7 |
| 亀沢1、2丁目合同 牛嶋神社 奉納踊り | 緑町公園 | regenerate_exact_via_season_hint_postprocess | 5 |
| 京橋盆踊り | 京橋エドグラン 京橋中央ひろば | regenerate_exact_via_season_hint_postprocess | 5 |
| 六本木ヒルズ盆踊り | 六本木ヒルズアリーナ | regenerate_exact_via_historical_reference_postprocess | 7 |
| 六本木天祖神社（龍土神明宮）例大祭 盆踊り | 六本木天祖神社 | regenerate_exact_via_season_hint_postprocess | 5 |
| 品川区民まつり 八潮地区 | 八潮公園 | regenerate_exact_via_season_hint_postprocess | 5 |
| 品川区民まつり 品川第二地区 | 城南小学校 | regenerate_exact_via_season_hint_postprocess | 5 |
| 品川区民まつり 大崎第一地区 | 第一日野小学校 | regenerate_exact_via_season_hint_postprocess | 5 |
| 品川区民まつり 大崎第一地区 | 第四日野小学校 | regenerate_exact_via_season_hint_postprocess | 5 |
| 品川区民まつり 荏原第一地区 | 小山台小学校 | regenerate_exact_via_season_hint_postprocess | 5 |
| 品川区民まつり 荏原第三地区 | 京陽小学校 | regenerate_exact_via_season_hint_postprocess | 5 |
| 品川区民まつり 荏原第四地区 | 上神明小学校 | regenerate_exact_via_season_hint_postprocess | 5 |
| 品川第二地区 区民まつり・品川青年会 盆踊り大会（天妙国寺） | 天妙国寺 | regenerate_exact_via_season_hint_postprocess | 5 |
| 増上寺 地蔵尊盆踊り大会 | 増上寺（大殿前広場） | regenerate_exact_via_season_hint_postprocess | 5 |

## Public Sync Guard

- status: pass
- safe_to_wholesale_sync: True
- failures: []
- warnings: []
- postprocessed_events_by_action: {'fixed_date_rule_basis_refresh': 1}

| action | event | venue | families | fields |
| --- | --- | --- | --- | ---: |

## Song Occurrence Collapse Analysis

- intentional_duplicate_collapse_count: 2
- review_required_count: 0
- missing_public_song_row_count: 2

| decision | event | venue | role | source_titles | exported_titles |
| --- | --- | --- | --- | --- | --- |
| intentional_duplicate_collapse | 山王音頭と民踊大会 | 赤坂日枝神社 | result | ダンシングヒーロー, ダンシング・ヒーロー | ダンシングヒーロー |
| intentional_duplicate_collapse | シタマチ.ふるさと盆踊り大会 | おかちまちパンダ広場（御徒町駅南口駅前広場） | prediction | かわいいだけじゃだめですか, かわいいだけじゃだめですか? | かわいいだけじゃだめですか |

## Public Individual Review Priority

- individual_review_event_count: 0
- p0_p1_event_count: 0
- by_priority: {}

| priority | bucket | event | venue | review_fields |
| --- | --- | --- | --- | ---: |

## Koto Review Request

From: おと（Codex）
To: こと（Claude Code）

Please review:

- Review scripts in A_scripts_review, especially dry_run_ph2_event_occurrence_apply.py safety gates.
- Review whether venue_review alias candidates can be accepted or need separate venue records.
- Review that only 品川区民まつり 荏原第一地区 is ready for actual DB apply before broader Ph2.
- Use public_diff_classification before any events_public.json sync decision.
- Use public_restore_candidate_breakdown: 76 restore candidates regenerate exactly via existing public post-processors.
- Use public_events_sync_guard.py as a blocking pre-sync check; current status passes with 0 postprocessed individual-review diffs.
- Treat the 2 missing public song rows as intentional duplicate collapse unless reviewer disagrees.
- Review public_individual_review_priority first: P0/P1 is 0 raw-diff events; use public_sync_guard blocking examples for the smaller postprocessed set.
- For public diffs: keep raw individual-review rows separate from postprocess-regenerated restore candidates.

Do not do without Uchida GO:

- write to Notion
- apply to data/bon_odori_master.sqlite
- deploy public site
- unfreeze legacy song occurrence generation
