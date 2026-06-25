# Master RDB -> Notion sync dry-run

- generated_at: 2026-06-25T13:46:34.371995+00:00
- mode: dry_run
- master_db: `data/bon_odori_master.sqlite`
- selected_jobs: 0
- ready_jobs: 0
- skipped_jobs: 0
- applied_jobs: 0
- issues_by_severity: {}

## Apply Sequence

1. RDB apply only: `<reviewed event name>` changes should land in the local master RDB.
2. Notion write-back is frozen; pending jobs are historical review material only.
3. Public output should be reviewed through the RDB-to-public export path.

This report does not authorize Notion writes.
RDB-to-Notion write-back is frozen by the RDB-only policy. Use dry-run output for historical review only; do not apply unless this is an explicit recovery operation.

| job | target | date | status | venue | page | result |
| --- | --- | --- | --- | --- | --- | --- |

## Field Diffs
