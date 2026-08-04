# Public events sync guard

**Note**: This guard checks for blocking diffs only. Guard status `pass` means no blocking issues remain, but is NOT a deploy approval. Deploy decisions require explicit confirmation from the operator.

- generated_at: 2026-08-04T00:52:40.653276+00:00
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

- collector_event_count: 309
- site_event_count: 308
- collector_only_count: 1
- site_only_count: 0
- high_risk_diff_record_count: 1
- high_risk_event_count: 1
- records_by_family: {'detail': 1}
- records_by_action: {'individual_review': 1}
- events_by_action: {'individual_review': 1}

## After Required Public Postprocessors

- collector_event_count: 309
- site_event_count: 308
- collector_only_count: 1
- site_only_count: 0
- high_risk_diff_record_count: 1
- high_risk_event_count: 1
- records_by_family: {'detail': 1}
- records_by_action: {'individual_review': 1}
- events_by_action: {'individual_review': 1}

## Reviewed Exact Approvals

- schema: public_sync_exact_approvals_v1
- status: pass
- approval_count: 169
- status_counts: {'already_synced': 159, 'inactive': 7, 'consumed_at_site': 1, 'applied': 2}
- failure_count: 0

## After Reviewed Exact Approvals

- collector_event_count: 309
- site_event_count: 309
- collector_only_count: 0
- site_only_count: 0
- high_risk_diff_record_count: 0
- high_risk_event_count: 0
- records_by_family: {}
- records_by_action: {}
- events_by_action: {}

## Automatically Allowed Ended Transitions

- count: 0

## Blocking Examples

| action | event | venue | families | fields |
| --- | --- | --- | --- | ---: |
