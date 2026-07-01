# Reviewed missing occurrence venues apply report

- generated_at: 2026-06-30T14:45:45.182297+00:00
- mode: apply
- target_db: `data/bon_odori_master.sqlite`
- dry_run_db: ``
- backup_db: `data/backups/bon_odori_master.20260630T144545.182297+0000.sqlite.bak`
- db_committed: True
- rolled_back: False
- applied_count: 1
- skipped_count: 0
- issues_by_severity: {}
- missing_venue_count: 3

| action | event | before | after | venue created | series usual venue updated | reason |
| --- | --- | --- | --- | --- | --- | --- |
| create_venue_and_fill_occurrence | 月島第二児童公園 盆踊り | (none) | 月島第二児童公園 (`ven_456beaee9aa43b0e`) | True | True | official Chuo City park/facility list confirms 月島第二児童公園 and address; event date/source is still unconfirmed, so this is venue-fill only |
