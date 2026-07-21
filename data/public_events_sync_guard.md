# Public events sync guard

**Note**: This guard checks for blocking diffs only. Guard status `pass` means no blocking issues remain, but is NOT a deploy approval. Deploy decisions require explicit confirmation from the operator.

- generated_at: 2026-07-21T07:08:33.459066+00:00
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

- collector_event_count: 209
- site_event_count: 209
- collector_only_count: 2
- site_only_count: 2
- high_risk_diff_record_count: 81
- high_risk_event_count: 21
- records_by_family: {'historical_slide': 37, 'date_prediction': 38, 'historical_reference': 4, 'detail': 1, 'source': 1}
- records_by_action: {'individual_review': 27, 'low_priority_or_unclassified': 38, 'restore_collector_from_site_or_reenable_export_postprocess': 16}
- events_by_action: {'individual_review': 19, 'expired_historical_slide_downgrade': 2}

## After Required Public Postprocessors

- collector_event_count: 209
- site_event_count: 209
- collector_only_count: 2
- site_only_count: 2
- high_risk_diff_record_count: 81
- high_risk_event_count: 21
- records_by_family: {'historical_slide': 37, 'date_prediction': 38, 'historical_reference': 4, 'detail': 1, 'source': 1}
- records_by_action: {'individual_review': 27, 'low_priority_or_unclassified': 38, 'restore_collector_from_site_or_reenable_export_postprocess': 16}
- events_by_action: {'individual_review': 19, 'expired_historical_slide_downgrade': 2}

## Reviewed Exact Approvals

- schema: public_sync_exact_approvals_v1
- status: pass
- approval_count: 21
- status_counts: {'applied': 21}
- failure_count: 0

## After Reviewed Exact Approvals

- collector_event_count: 209
- site_event_count: 209
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
