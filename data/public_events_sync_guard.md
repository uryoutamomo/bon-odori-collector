# Public events sync guard

**Note**: This guard checks for blocking diffs only. Guard status `pass` means no blocking issues remain, but is NOT a deploy approval. Deploy decisions require explicit confirmation from the operator.

- generated_at: 2026-07-26T02:45:47.411467+00:00
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

- collector_event_count: 203
- site_event_count: 209
- collector_only_count: 0
- site_only_count: 6
- high_risk_diff_record_count: 158
- high_risk_event_count: 18
- records_by_family: {'historical_slide': 122, 'historical_reference': 26, 'date_prediction': 10}
- records_by_action: {'individual_review': 44, 'restore_collector_from_site_or_reenable_export_postprocess': 104, 'low_priority_or_unclassified': 10}
- events_by_action: {'expired_historical_slide_downgrade': 13, 'individual_review': 5}

## After Required Public Postprocessors

- collector_event_count: 203
- site_event_count: 209
- collector_only_count: 0
- site_only_count: 6
- high_risk_diff_record_count: 158
- high_risk_event_count: 18
- records_by_family: {'historical_slide': 122, 'historical_reference': 26, 'date_prediction': 10}
- records_by_action: {'individual_review': 44, 'restore_collector_from_site_or_reenable_export_postprocess': 104, 'low_priority_or_unclassified': 10}
- events_by_action: {'expired_historical_slide_downgrade': 13, 'individual_review': 5}

## Reviewed Exact Approvals

- schema: public_sync_exact_approvals_v1
- status: block
- approval_count: 35
- status_counts: {'already_synced': 17, 'hash_mismatch': 3, 'applied': 15}
- failure_count: 3

## After Reviewed Exact Approvals

- collector_event_count: 203
- site_event_count: 203
- collector_only_count: 0
- site_only_count: 0
- high_risk_diff_record_count: 102
- high_risk_event_count: 10
- records_by_family: {'historical_slide': 82, 'historical_reference': 18, 'date_prediction': 2}
- records_by_action: {'individual_review': 28, 'restore_collector_from_site_or_reenable_export_postprocess': 72, 'low_priority_or_unclassified': 2}
- events_by_action: {'expired_historical_slide_downgrade': 9, 'individual_review': 1}

## Blocking Examples

| action | event | venue | families | fields |
| --- | --- | --- | --- | ---: |
| individual_review | 第51回 浄土寺盆踊り大会 | 浄土寺 | date_prediction, historical_slide | 3 |
