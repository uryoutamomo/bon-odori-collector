# Public events sync guard

**Note**: This guard checks for blocking diffs only. Guard status `pass` means no blocking issues remain, but is NOT a deploy approval. Deploy decisions require explicit confirmation from the operator.

- generated_at: 2026-06-22T02:16:05.121237+00:00
- scope: read_only_public_sync_guard_no_writes
- status: block
- safe_to_wholesale_sync: False
- safe_to_deploy_without_review: False
- public_deploy_requires_separate_approval: True
- deploy_approval_note: Guard pass only means no blocking public sync diffs remain. Public deploy still requires separate operator approval.
- failures: ['event_count_mismatch', 'event_key_mismatch', 'individual_review_diffs_remain']
- warnings: []

## Raw Collector vs Site

- collector_event_count: 183
- site_event_count: 182
- collector_only_count: 2
- site_only_count: 1
- high_risk_diff_record_count: 43
- high_risk_event_count: 5
- records_by_family: {'detail': 1, 'historical_slide': 19, 'historical_reference': 11, 'date_prediction': 7, 'season_hint': 5}
- records_by_action: {'individual_review': 14, 'restore_collector_from_site_or_reenable_export_postprocess': 24, 'low_priority_or_unclassified': 3, 'site_update_candidate_after_review': 2}
- events_by_action: {'individual_review': 2, 'low_priority_or_unclassified': 1, 'rule_prediction_replaces_matching_historical_slide': 1, 'fixed_date_rule_basis_refresh': 1}

## After Required Public Postprocessors

- collector_event_count: 183
- site_event_count: 182
- collector_only_count: 2
- site_only_count: 1
- high_risk_diff_record_count: 43
- high_risk_event_count: 5
- records_by_family: {'detail': 1, 'historical_slide': 19, 'historical_reference': 11, 'date_prediction': 7, 'season_hint': 5}
- records_by_action: {'individual_review': 14, 'restore_collector_from_site_or_reenable_export_postprocess': 24, 'low_priority_or_unclassified': 3, 'site_update_candidate_after_review': 2}
- events_by_action: {'individual_review': 2, 'low_priority_or_unclassified': 1, 'rule_prediction_replaces_matching_historical_slide': 1, 'fixed_date_rule_basis_refresh': 1}

## Blocking Examples

| action | event | venue | families | fields |
| --- | --- | --- | --- | ---: |
| individual_review | 三角広場まつり「居酒屋盆踊り」 | 新宿住友ビル三角広場 | date_prediction, detail, historical_reference, historical_slide | 19 |
| individual_review | 品川区民まつり 荏原第一地区 | 小山台小学校 | date_prediction, historical_slide, season_hint | 8 |
