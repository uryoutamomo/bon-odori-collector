# Public events sync guard

**Note**: This guard checks for blocking diffs only. Guard status `pass` means no blocking issues remain, but is NOT a deploy approval. Deploy decisions require explicit confirmation from the operator.

- generated_at: 2026-06-22T01:22:17.924924+00:00
- scope: read_only_public_sync_guard_no_writes
- status: pass
- safe_to_wholesale_sync: True
- safe_to_deploy_without_review: False
- public_deploy_requires_separate_approval: True
- deploy_approval_note: Guard pass only means no blocking public sync diffs remain. Public deploy still requires separate operator approval.
- failures: []
- warnings: []

## Raw Collector vs Site

- collector_event_count: 182
- site_event_count: 182
- collector_only_count: 0
- site_only_count: 0
- high_risk_diff_record_count: 0
- high_risk_event_count: 0
- records_by_family: {}
- records_by_action: {}
- events_by_action: {}

## After Required Public Postprocessors

- collector_event_count: 182
- site_event_count: 182
- collector_only_count: 0
- site_only_count: 0
- high_risk_diff_record_count: 5
- high_risk_event_count: 1
- records_by_family: {'historical_reference': 2, 'historical_slide': 3}
- records_by_action: {'individual_review': 5}
- events_by_action: {'fixed_date_rule_basis_refresh': 1}

## Blocking Examples

| action | event | venue | families | fields |
| --- | --- | --- | --- | ---: |
