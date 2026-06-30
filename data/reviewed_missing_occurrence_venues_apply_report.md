# Reviewed missing occurrence venues apply report

- generated_at: 2026-06-30T03:15:44.398169+00:00
- mode: dry_run
- target_db: `data/reviewed_missing_occurrence_venues_dry_run.sqlite`
- dry_run_db: `data/reviewed_missing_occurrence_venues_dry_run.sqlite`
- backup_db: ``
- db_committed: True
- rolled_back: False
- applied_count: 1
- skipped_count: 0
- issues_by_severity: {}
- missing_venue_count: 6

| action | event | before | after | venue created | series usual venue updated | reason |
| --- | --- | --- | --- | --- | --- | --- |
| create_venue_and_fill_occurrence | 銀座一丁目東町会・新富町会 納涼盆踊り大会 | (none) | 京橋プラザ区民館 (`ven_3823a14944e4649f`) | True | True | official Chuo City facility page confirms 京橋プラザ区民館, and multiple observed YouTube evidence rows confirm the 2025 event/date/organizers at 京橋プラザ |
