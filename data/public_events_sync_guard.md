# Public events sync guard

**Note**: This guard checks for blocking diffs only. Guard status `pass` means no blocking issues remain, but is NOT a deploy approval. Deploy decisions require explicit confirmation from the operator.

- generated_at: 2026-07-24T10:12:18.433869+00:00
- scope: read_only_public_sync_guard_no_writes
- status: block
- safe_to_wholesale_sync: False
- public_deploy_requires_separate_approval: True
- deploy_approval_note: Guard pass only means no blocking public sync diffs remain. Public deploy still requires separate operator approval.
- failures: ['individual_review_diffs_remain', 'reviewed_exact_approval_mismatch']
- warnings: []
- procedure_warnings: []

## Procedure Warnings

These warnings mean the public-event publication flow may have skipped a review step. They do not automatically approve or reject deploys; they should be resolved or consciously accepted before syncing/deploying.

- none

## Raw Collector vs Site

- collector_event_count: 209
- site_event_count: 209
- collector_only_count: 0
- site_only_count: 0
- high_risk_diff_record_count: 113
- high_risk_event_count: 24
- records_by_family: {'historical_slide': 64, 'date_prediction': 38, 'historical_reference': 10, 'detail': 1}
- records_by_action: {'individual_review': 35, 'low_priority_or_unclassified': 38, 'restore_collector_from_site_or_reenable_export_postprocess': 40}
- events_by_action: {'individual_review': 19, 'expired_historical_slide_downgrade': 5}

## After Required Public Postprocessors

- collector_event_count: 209
- site_event_count: 209
- collector_only_count: 0
- site_only_count: 0
- high_risk_diff_record_count: 113
- high_risk_event_count: 24
- records_by_family: {'historical_slide': 64, 'date_prediction': 38, 'historical_reference': 10, 'detail': 1}
- records_by_action: {'individual_review': 35, 'low_priority_or_unclassified': 38, 'restore_collector_from_site_or_reenable_export_postprocess': 40}
- events_by_action: {'individual_review': 19, 'expired_historical_slide_downgrade': 5}

## Reviewed Exact Approvals

- schema: public_sync_exact_approvals_v1
- status: block
- approval_count: 21
- status_counts: {'applied': 13, 'hash_mismatch': 8}
- failure_count: 8

## After Reviewed Exact Approvals

- collector_event_count: 209
- site_event_count: 209
- collector_only_count: 0
- site_only_count: 0
- high_risk_diff_record_count: 74
- high_risk_event_count: 11
- records_by_family: {'historical_slide': 51, 'historical_reference': 10, 'date_prediction': 12, 'detail': 1}
- records_by_action: {'individual_review': 22, 'restore_collector_from_site_or_reenable_export_postprocess': 40, 'low_priority_or_unclassified': 12}
- events_by_action: {'expired_historical_slide_downgrade': 5, 'individual_review': 6}

## Blocking Examples

| action | event | venue | families | fields |
| --- | --- | --- | --- | ---: |
| individual_review | 大和町八幡神社大盆踊り会 | 中野大和町八幡神社 | date_prediction, historical_slide | 3 |
| individual_review | 神楽坂夏まつり 盆踊り in 神楽坂 | りそな銀行神楽坂支店前 | date_prediction, detail, historical_slide | 4 |
| individual_review | 第26回 四谷納涼踊り大会 | 四谷ひろばグランド（旧四谷第四小） | date_prediction, historical_slide | 3 |
| individual_review | 第2回 晴海ふ頭公園盆踊り大会 | 晴海ふ頭公園 | date_prediction, historical_slide | 3 |
| individual_review | 自由が丘納涼盆踊り大会 | 自由が丘駅前ロータリー 特設会場 | date_prediction, historical_slide | 3 |
| individual_review | 郡上おどり in 青山 | 秩父宮ラグビー場駐車場 | date_prediction, historical_slide | 3 |
