# Public events sync guard

**Note**: This guard checks for blocking diffs only. Guard status `pass` means no blocking issues remain, but is NOT a deploy approval. Deploy decisions require explicit confirmation from the operator.

- generated_at: 2026-07-24T11:00:46.143881+00:00
- scope: read_only_public_sync_guard_no_writes
- status: block
- safe_to_wholesale_sync: False
- public_deploy_requires_separate_approval: True
- deploy_approval_note: Guard pass only means no blocking public sync diffs remain. Public deploy still requires separate operator approval.
- failures: ['individual_review_diffs_remain', 'reviewed_exact_approval_mismatch']
- warnings: ['master_rdb_newer_than_publication_gap_review']
- procedure_warnings: ['master_rdb_newer_than_publication_gap_review']

## Procedure Warnings

These warnings mean the public-event publication flow may have skipped a review step. They do not automatically approve or reject deploys; they should be resolved or consciously accepted before syncing/deploying.

- master_rdb_newer_than_publication_gap_review

## Raw Collector vs Site

- collector_event_count: 209
- site_event_count: 209
- collector_only_count: 0
- site_only_count: 0
- high_risk_diff_record_count: 40
- high_risk_event_count: 7
- records_by_family: {'historical_slide': 27, 'historical_reference': 6, 'detail': 4, 'source': 3}
- records_by_action: {'individual_review': 16, 'restore_collector_from_site_or_reenable_export_postprocess': 24}
- events_by_action: {'expired_historical_slide_downgrade': 3, 'individual_review': 4}

## After Required Public Postprocessors

- collector_event_count: 209
- site_event_count: 209
- collector_only_count: 0
- site_only_count: 0
- high_risk_diff_record_count: 40
- high_risk_event_count: 7
- records_by_family: {'historical_slide': 27, 'historical_reference': 6, 'detail': 4, 'source': 3}
- records_by_action: {'individual_review': 16, 'restore_collector_from_site_or_reenable_export_postprocess': 24}
- events_by_action: {'expired_historical_slide_downgrade': 3, 'individual_review': 4}

## Reviewed Exact Approvals

- schema: public_sync_exact_approvals_v1
- status: block
- approval_count: 21
- status_counts: {'already_synced': 17, 'hash_mismatch': 4}
- failure_count: 4

## After Reviewed Exact Approvals

- collector_event_count: 209
- site_event_count: 209
- collector_only_count: 0
- site_only_count: 0
- high_risk_diff_record_count: 40
- high_risk_event_count: 7
- records_by_family: {'historical_slide': 27, 'historical_reference': 6, 'detail': 4, 'source': 3}
- records_by_action: {'individual_review': 16, 'restore_collector_from_site_or_reenable_export_postprocess': 24}
- events_by_action: {'expired_historical_slide_downgrade': 3, 'individual_review': 4}

## Blocking Examples

| action | event | venue | families | fields |
| --- | --- | --- | --- | ---: |
| individual_review | 新宿中央公園夏祭り 納涼盆踊り大会 | 新宿中央公園 ファンモアタイムひろば | detail, source | 2 |
| individual_review | 神楽坂夏まつり 盆踊り in 神楽坂 | りそな銀行神楽坂支店前 | detail | 1 |
| individual_review | 第16回 鴨台盆踊り | 大正大学 | detail, source | 2 |
| individual_review | 自由が丘納涼盆踊り大会 | 自由が丘駅前ロータリー 特設会場 | detail, source | 2 |
