# Master RDB -> Notion sync dry-run

- generated_at: 2026-06-22T14:49:40.663691+00:00
- mode: dry_run
- master_db: `data/bon_odori_master.sqlite`
- selected_jobs: 0
- ready_jobs: 0
- skipped_jobs: 0
- applied_jobs: 0
- issues_by_severity: {}

## Apply Sequence

1. RDB apply only: `python3 dry_run_ph2_event_occurrence_apply.py --apply --event-name '<reviewed event name>' --confirm 'APPLY PH2 EVENT OCCURRENCE'`
2. Refresh Notion snapshot immediately before Notion apply: `python3 build_notion_rdb.py`
3. Notion sync only after review: `python3 sync_master_to_notion.py --requested-by dry_run_ph2_event_occurrence_apply.py --apply --confirm 'APPLY RDB TO NOTION'`

Both apply steps require separate review and explicit approval before running against production inputs.
The snapshot refresh is mandatory because drift detection uses `data/notion_snapshot.sqlite`.

| job | target | date | status | venue | page | result |
| --- | --- | --- | --- | --- | --- | --- |

## Field Diffs
