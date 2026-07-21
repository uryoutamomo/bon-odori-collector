# Change requests apply result

- generated_at: 2026-07-21T03:08:47.069530+00:00
- mode: dry_run
- requests_applied: 3
- requests_unresolved: 0
- target_db: `data/change_requests_apply_dry_run.sqlite`
- dry_run_db: `data/change_requests_apply_dry_run.sqlite`
- backup_db: ``
- db_committed: True
- rolled_back: False
- issues_by_severity: {}
- audit_issues_by_severity: {}

## Applied requests

- ohdai_2026_create_current_occurrence `create_current_year_occurrence` occurrence=occ_63ae1b3a246f34f0
- shinjuku_chuo_2026_confirm_date `confirm_current_year_date` occurrence=occ_99e2dd44bce470e3
- jiyugaoka_2026_add_official_confirmation `confirm_current_year_date` occurrence=occ_0240108c92fd793b

## Next step

- Medium issues mean those requests were skipped; fix the JSON and re-run.
- High issues roll back the whole transaction.
- Public JSON and site deploy remain separate and follow the one-a-day publish rule.
