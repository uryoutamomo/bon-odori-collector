# Public events diff classification

- generated_at: 2026-06-22T02:16:04.912461+00:00
- scope: read_only_diff_classification_no_writes
- collector_event_count: 183
- site_event_count: 182
- collector_only_count: 2
- site_only_count: 1
- high_risk_event_count: 5
- high_risk_diff_record_count: 43
- records_by_family: {'detail': 1, 'historical_slide': 19, 'historical_reference': 11, 'date_prediction': 7, 'season_hint': 5}
- records_by_action: {'individual_review': 14, 'restore_collector_from_site_or_reenable_export_postprocess': 24, 'low_priority_or_unclassified': 3, 'site_update_candidate_after_review': 2}
- events_by_action: {'fixed_date_rule_basis_refresh': 1, 'individual_review': 2, 'low_priority_or_unclassified': 1, 'rule_prediction_replaces_matching_historical_slide': 1}

## Action Buckets

### individual_review

| event | venue | families | fields |
| --- | --- | --- | ---: |
| 三角広場まつり「居酒屋盆踊り」 | 新宿住友ビル三角広場 | date_prediction, detail, historical_reference, historical_slide | 19 |
| 品川区民まつり 荏原第一地区 | 小山台小学校 | date_prediction, historical_slide, season_hint | 8 |

### rule_prediction_replaces_matching_historical_slide

| event | venue | families | fields |
| --- | --- | --- | ---: |
| 歌舞伎町BON ODORI | 歌舞伎町シネシティ広場 | date_prediction, historical_reference, historical_slide | 10 |

### fixed_date_rule_basis_refresh

| event | venue | families | fields |
| --- | --- | --- | ---: |
| 花園神社 盆踊り | 花園神社 | historical_reference, historical_slide | 5 |

### low_priority_or_unclassified

| event | venue | families | fields |
| --- | --- | --- | ---: |
| 品川区民まつり 荏原第五地区 | 杜松ホーム | date_prediction | 1 |

## Field-Level Site Update Candidates

These collector-only fields may be copied to site after individual review, but their events may still have other mixed diffs.

| event | venue | field | collector | site |
| --- | --- | --- | --- | --- |
| 歌舞伎町BON ODORI | 歌舞伎町シネシティ広場 | date_prediction | {"display_tier": "rule_predicted", "confidence": "medium", "score": 0.7, "date": "2026-08-15", "date_end": "2026-08-15", "basis": "8月第3土曜", "rule_type": "weekday_nth"} | null |
| 歌舞伎町BON ODORI | 歌舞伎町シネシティ広場 | prediction_evidence_years | [2024, 2025] | null |

## Individual Review Details

| event | venue | field | side | collector | site |
| --- | --- | --- | --- | --- | --- |
| 三角広場まつり「居酒屋盆踊り」 | 新宿住友ビル三角広場 | detail | both_different | "新宿住友ビル三角広場公式告知。キュー上の「新宿住友ビル三角広場まつり居酒屋盆踊り」は同一候補として処理。 【2026年確定】2026/06/24(水)〜06/25(木)開催。出典: （こと 2026-06-21 公式サイト直接確認）。タグ: 電車圏／夜開催（1日3回盆踊りタイム）" | "新宿住友ビル三角広場公式告知。キュー上の「新宿住友ビル三角広場まつり居酒屋盆踊り」は同一候補として処理。" |
| 三角広場まつり「居酒屋盆踊り」 | 新宿住友ビル三角広場 | display_tier | both_different | "confirmed" | "historical_slide" |
| 三角広場まつり「居酒屋盆踊り」 | 新宿住友ビル三角広場 | recurrence_score | both_different | 0.95 | 0.63 |
| 品川区民まつり 荏原第一地区 | 小山台小学校 | display_tier | both_different | "confirmed" | "season_hint" |
| 品川区民まつり 荏原第一地区 | 小山台小学校 | recurrence_score | both_different | 0.95 | 0.25 |
| 歌舞伎町BON ODORI | 歌舞伎町シネシティ広場 | display_tier | both_different | "rule_predicted" | "historical_slide" |
| 歌舞伎町BON ODORI | 歌舞伎町シネシティ広場 | historical_display_tier | both_different | "historical_reference" | "historical_slide" |
| 歌舞伎町BON ODORI | 歌舞伎町シネシティ広場 | historical_reference | both_different | {"display_tier": "historical_reference", "label": "2025-08-16実績・今年未確認", "confidence": "medium", "score": 0.6, "last_seen_year": 2025, "last_seen_dates": ["2025-08-16"]} | {"display_tier": "historical_slide", "label": "2025-08-16実績・今年未確認", "confidence": "medium", "score": 0.6, "last_seen_year": 2025, "last_seen_dates": ["2025-08-16"]} |
| 歌舞伎町BON ODORI | 歌舞伎町シネシティ広場 | prediction_basis | both_different | "8月第3土曜" | "2025年実績の同月第3土曜を2026年へスライド" |
| 花園神社 盆踊り | 花園神社 | historical_reference | both_different | {"display_tier": "historical_slide", "label": "2025-08-01〜2025-08-02実績・今年未確認", "confidence": "medium", "score": 0.55, "last_seen_year": 2025, "last_seen_dates": ["2025-08-01", "2025-08-02"]} | {"display_tier": "historical_slide", "label": "2025-08-01〜2025-08-02実績・今年未確認", "confidence": "medium", "score": 0.59, "last_seen_year": 2025, "last_seen_dates": ["2025-08-01", "2025-08-02"]} |
| 花園神社 盆踊り | 花園神社 | historical_reference_score | both_different | 0.55 | 0.59 |
| 花園神社 盆踊り | 花園神社 | historical_slide | both_different | {"date": "2026-08-01", "date_end": "2026-08-02", "basis": "YOKOSO新宿の告知に「毎年8月1日・2日」と明記", "rule_type": "fixed_date_range"} | {"date": "2026-08-01", "date_end": "2026-08-02", "basis": "イベントDBの固定日カラムに記録", "rule_type": "fixed_date_range"} |
| 花園神社 盆踊り | 花園神社 | historical_slide_basis | both_different | "YOKOSO新宿の告知に「毎年8月1日・2日」と明記" | "イベントDBの固定日カラムに記録" |
| 花園神社 盆踊り | 花園神社 | prediction_basis | both_different | "YOKOSO新宿の告知に「毎年8月1日・2日」と明記" | "イベントDBの固定日カラムに記録" |
