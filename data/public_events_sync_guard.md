# Public events sync guard

**Note**: This guard checks for blocking diffs only. Guard status `pass` means no blocking issues remain, but is NOT a deploy approval. Deploy decisions require explicit confirmation from the operator.

- generated_at: 2026-08-01T01:30:12.685358+00:00
- scope: read_only_public_sync_guard_no_writes
- status: block
- safe_to_wholesale_sync: False
- public_deploy_requires_separate_approval: True
- deploy_approval_note: Guard pass only means no blocking public sync diffs remain. Public deploy still requires separate operator approval.
- failures: ['event_count_mismatch', 'event_key_mismatch']
- warnings: ['master_rdb_newer_than_publication_gap_review']
- procedure_warnings: ['master_rdb_newer_than_publication_gap_review']

## Procedure Warnings

These warnings mean the public-event publication flow may have skipped a review step. They do not automatically approve or reject deploys; they should be resolved or consciously accepted before syncing/deploying.

- master_rdb_newer_than_publication_gap_review

## Raw Collector vs Site

- collector_event_count: 258
- site_event_count: 251
- collector_only_count: 7
- site_only_count: 0
- high_risk_diff_record_count: 0
- high_risk_event_count: 0
- records_by_family: {}
- records_by_action: {}
- events_by_action: {}

## After Required Public Postprocessors

- collector_event_count: 258
- site_event_count: 251
- collector_only_count: 7
- site_only_count: 0
- high_risk_diff_record_count: 0
- high_risk_event_count: 0
- records_by_family: {}
- records_by_action: {}
- events_by_action: {}

## Reviewed Exact Approvals

- schema: public_sync_exact_approvals_v1
- status: pass
- approval_count: 56
- status_counts: {'already_synced': 49, 'inactive': 7}
- failure_count: 0

## After Reviewed Exact Approvals

- collector_event_count: 258
- site_event_count: 251
- collector_only_count: 7
- site_only_count: 0
- high_risk_diff_record_count: 0
- high_risk_event_count: 0
- records_by_family: {}
- records_by_action: {}
- events_by_action: {}

## Blocking Examples

| action | event | venue | families | fields |
| --- | --- | --- | --- | ---: |
