# Change requests apply result

- generated_at: 2026-08-17T14:30:47.714673+00:00
- mode: apply
- requests_applied: 1
- requests_unresolved: 0
- target_db: `data/bon_odori_master.sqlite`
- dry_run_db: ``
- backup_db: `data/backups/bon_odori_master.20260817T143047.714673+0000.sqlite.bak`
- db_committed: True
- rolled_back: False
- issues_by_severity: {}
- audit_issues_by_severity: {}

## Applied requests

- oedo_matsuri_2025_youtube_setlist_j0tAIB1dOig `add_song_evidence` occurrence=occ_748784f87c0cce79

## Next step

- Medium issues mean those requests were skipped; fix the JSON and re-run.
- High issues roll back the whole transaction.
- Public JSON and site deploy remain separate and follow the one-a-day publish rule.
