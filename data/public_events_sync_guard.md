# Public events sync guard

**Note**: This guard checks for blocking diffs only. Guard status `pass` means no blocking issues remain, but is NOT a deploy approval. Deploy decisions require explicit confirmation from the operator.

- generated_at: 2026-08-08T02:28:59.970148+00:00
- scope: read_only_public_sync_guard_no_writes
- status: pass
- safe_to_wholesale_sync: True
- public_deploy_requires_separate_approval: True
- deploy_approval_note: Guard pass only means no blocking public sync diffs remain. Public deploy still requires separate operator approval.
- failures: []
- warnings: ['master_rdb_newer_than_publication_gap_review']
- procedure_warnings: ['master_rdb_newer_than_publication_gap_review']

## Procedure Warnings

These warnings mean the public-event publication flow may have skipped a review step. They do not automatically approve or reject deploys; they should be resolved or consciously accepted before syncing/deploying.

- master_rdb_newer_than_publication_gap_review

## Raw Collector vs Site

- collector_event_count: 370
- site_event_count: 369
- collector_only_count: 1
- site_only_count: 0
- high_risk_diff_record_count: 40
- high_risk_event_count: 7
- records_by_family: {'schedule': 2, 'detail': 3, 'historical_slide': 17, 'historical_reference': 11, 'date_prediction': 6, 'source': 1}
- records_by_action: {'individual_review': 12, 'restore_collector_from_site_or_reenable_export_postprocess': 23, 'low_priority_or_unclassified': 5}
- events_by_action: {'individual_review': 3, 'low_priority_or_unclassified': 2, 'expired_historical_slide_downgrade': 2}

## After Required Public Postprocessors

- collector_event_count: 370
- site_event_count: 369
- collector_only_count: 1
- site_only_count: 0
- high_risk_diff_record_count: 42
- high_risk_event_count: 7
- records_by_family: {'schedule': 2, 'detail': 3, 'historical_slide': 19, 'historical_reference': 11, 'date_prediction': 6, 'source': 1}
- records_by_action: {'individual_review': 14, 'restore_collector_from_site_or_reenable_export_postprocess': 23, 'low_priority_or_unclassified': 5}
- events_by_action: {'individual_review': 3, 'low_priority_or_unclassified': 2, 'expired_historical_slide_downgrade': 2}

## Reviewed Exact Approvals

- schema: public_sync_exact_approvals_v1
- status: pass
- approval_count: 233
- status_counts: {'already_synced': 214, 'inactive': 7, 'already_applied': 8, 'applied': 4}
- failure_count: 0

## After Reviewed Exact Approvals

- collector_event_count: 370
- site_event_count: 370
- collector_only_count: 0
- site_only_count: 0
- high_risk_diff_record_count: 26
- high_risk_event_count: 4
- records_by_family: {'date_prediction': 4, 'historical_slide': 18, 'historical_reference': 4}
- records_by_action: {'low_priority_or_unclassified': 4, 'individual_review': 6, 'restore_collector_from_site_or_reenable_export_postprocess': 16}
- events_by_action: {'low_priority_or_unclassified': 2, 'expired_historical_slide_downgrade': 2}

## Automatically Allowed Ended Transitions

- count: 0

## Blocking Examples

| action | event | venue | families | fields |
| --- | --- | --- | --- | ---: |
