# Reviewed official-wait events apply report

- generated_at: 2026-06-30T14:09:38.965329+00:00
- mode: apply
- target_db: `data/bon_odori_master.sqlite`
- dry_run_db: `data/reviewed_official_wait_events_dry_run.sqlite`
- backup_db: `data/backups/bon_odori_master.20260630T140938.965329+0000.sqlite.bak`
- db_committed: True
- rolled_back: False
- applied_count: 0
- skipped_count: 1
- issues_by_severity: {}

| event | before | after | venue | date | source |
| --- | --- | --- | --- | --- | --- |

## Skipped

| event | reason |
| --- | --- |
| 鉄砲洲納涼盆踊り | already_applied |
