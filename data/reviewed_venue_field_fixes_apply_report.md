# Reviewed venue field fixes apply report

- generated_at: 2026-06-22T04:41:21.228955+00:00
- mode: apply
- target_db: `data/bon_odori_master.sqlite`
- dry_run_db: ``
- backup_db: `data/backups/bon_odori_master.20260622T044121.228955+0000.sqlite.bak`
- db_committed: True
- rolled_back: False
- applied_count: 3
- skipped_count: 0
- issues_by_severity: {}
- missing_venue_count: 7
- missing_date_start_count: 80

| action | event | venue | date update | reason |
| --- | --- | --- | --- | --- |
| fill_existing_venue | マロニエまつり盆踊り大会 | ヒューリック浅草橋ビル前 (`ven_e82a2aed94e45d29`) | (none) | same-date curated 浅草橋マロニエまつり盆踊り occurrence already uses ヒューリック浅草橋ビル前 |
| fill_existing_venue | 新橋こいち祭 | 桜田公園 (`ven_331b917a98238b0d`) | (none) | same official source and prior curated 第28回新橋こいち祭 盆踊り occurrence use 桜田公園 |
| create_venue_and_fill_occurrence | 中野駅前大盆踊り大会 | 中野セントラルパーク (`ven_c1a0d7dbd4fae8d5`) | 2026-08-01 to 2026-08-02 | 2026 official site confirms 中野セントラルパーク and 2026-08-01 to 2026-08-02 |
