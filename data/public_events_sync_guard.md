# Public events sync guard

**Note**: This guard checks for blocking diffs only. Guard status `pass` means no blocking issues remain, but is NOT a deploy approval. Deploy decisions require explicit confirmation from the operator.

- generated_at: 2026-07-29T04:40:35.031210+00:00
- scope: read_only_public_sync_guard_no_writes
- status: pass
- safe_to_wholesale_sync: True
- public_deploy_requires_separate_approval: True
- deploy_approval_note: Guard pass only means no blocking public sync diffs remain. Public deploy still requires separate operator approval.
- failures: []
- warnings: []
- procedure_warnings: []

## Procedure Warnings

These warnings mean the public-event publication flow may have skipped a review step. They do not automatically approve or reject deploys; they should be resolved or consciously accepted before syncing/deploying.

- none

## Raw Collector vs Site

- collector_event_count: 218
- site_event_count: 203
- collector_only_count: 42
- site_only_count: 27
- high_risk_diff_record_count: 142
- high_risk_event_count: 14
- records_by_family: {'detail': 8, 'historical_slide': 57, 'historical_reference': 39, 'date_prediction': 26, 'source': 2, 'season_hint': 10}
- records_by_action: {'individual_review': 35, 'restore_collector_from_site_or_reenable_export_postprocess': 91, 'low_priority_or_unclassified': 16}
- events_by_action: {'individual_review': 12, 'expired_historical_slide_downgrade': 2}

## After Required Public Postprocessors

- collector_event_count: 218
- site_event_count: 203
- collector_only_count: 42
- site_only_count: 27
- high_risk_diff_record_count: 143
- high_risk_event_count: 14
- records_by_family: {'detail': 8, 'historical_slide': 58, 'historical_reference': 39, 'date_prediction': 26, 'source': 2, 'season_hint': 10}
- records_by_action: {'individual_review': 36, 'restore_collector_from_site_or_reenable_export_postprocess': 91, 'low_priority_or_unclassified': 16}
- events_by_action: {'individual_review': 12, 'expired_historical_slide_downgrade': 2}

## Reviewed Exact Approvals

- schema: public_sync_exact_approvals_v1
- status: pass
- approval_count: 84
- status_counts: {'already_synced': 23, 'inactive': 6, 'applied': 55}
- failure_count: 0

## After Reviewed Exact Approvals

- collector_event_count: 218
- site_event_count: 218
- collector_only_count: 0
- site_only_count: 0
- high_risk_diff_record_count: 22
- high_risk_event_count: 2
- records_by_family: {'historical_slide': 18, 'historical_reference': 4}
- records_by_action: {'individual_review': 6, 'restore_collector_from_site_or_reenable_export_postprocess': 16}
- events_by_action: {'expired_historical_slide_downgrade': 2}

## Blocking Examples

| action | event | venue | families | fields |
| --- | --- | --- | --- | ---: |
