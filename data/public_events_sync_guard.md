# Public events sync guard

**Note**: This guard checks for blocking diffs only. Guard status `pass` means no blocking issues remain, but is NOT a deploy approval. Deploy decisions require explicit confirmation from the operator.

- generated_at: 2026-07-24T12:03:51.018137+00:00
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
- collector_only_count: 0
- site_only_count: 0
- high_risk_diff_record_count: 33
- high_risk_event_count: 3
- records_by_family: {'historical_slide': 27, 'historical_reference': 6}
- records_by_action: {'individual_review': 9, 'restore_collector_from_site_or_reenable_export_postprocess': 24}
- events_by_action: {'expired_historical_slide_downgrade': 3}

## After Required Public Postprocessors

- collector_event_count: 209
- site_event_count: 209
- collector_only_count: 0
- site_only_count: 0
- high_risk_diff_record_count: 33
- high_risk_event_count: 3
- records_by_family: {'historical_slide': 27, 'historical_reference': 6}
- records_by_action: {'individual_review': 9, 'restore_collector_from_site_or_reenable_export_postprocess': 24}
- events_by_action: {'expired_historical_slide_downgrade': 3}

## Reviewed Exact Approvals

- schema: public_sync_exact_approvals_v1
- status: pass
- approval_count: 20
- status_counts: {'already_synced': 20}
- failure_count: 0

## After Reviewed Exact Approvals

- collector_event_count: 209
- site_event_count: 209
- collector_only_count: 0
- site_only_count: 0
- high_risk_diff_record_count: 33
- high_risk_event_count: 3
- records_by_family: {'historical_slide': 27, 'historical_reference': 6}
- records_by_action: {'individual_review': 9, 'restore_collector_from_site_or_reenable_export_postprocess': 24}
- events_by_action: {'expired_historical_slide_downgrade': 3}

## Blocking Examples

| action | event | venue | families | fields |
| --- | --- | --- | --- | ---: |
