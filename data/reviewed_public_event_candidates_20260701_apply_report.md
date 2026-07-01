# Reviewed public event candidates 20260701 apply report

- generated_at: 2026-07-01T11:11:22.051224+00:00
- mode: apply
- target_db: `data/bon_odori_master.sqlite`
- dry_run_db: ``
- backup_db: `data/backups/bon_odori_master.20260701T111122.051224+0000.sqlite.bak`
- db_committed: True
- rolled_back: False
- applied_count: 5
- issues_by_severity: {}
- missing_publication_blocker_count: 71

| action | event | result | reason |
| --- | --- | --- | --- |
| merge_duplicate | 品川第二地区 区民まつり・品川青年会 盆踊り大会（天妙国寺） | merged `occ_df78a1d188e68698` into `occ_da7ddce69ae96791` | same 2026 Shinagawa district event is already confirmed as 品川区民まつり 品川第二地区 |
| merge_duplicate | えどぐらん（江東区） | merged `occ_ef4845b7ed9ac900` into `occ_07f775ba65031a6e` | source URL is the 京橋盆踊り2025 page; the 江東区/えどぐらん row is a misnamed duplicate |
| update_existing_event | 木場二丁目 盆踊り大会 | 2026-07-17 to 2026-07-18 at `ven_4841416eec0bedc4` | current-year Instagram announcement gives date, time, and venue; venue already exists in master RDB |
| update_existing_event | 木場一・六町会 盆踊り大会 | 2026-07-18 to 2026-07-19 at `ven_2985baea4a511ed8` | current-year local article contains a press-release style event outline with organizer, date, time, and venue |
| update_existing_event | 東陽一丁目町会 盆踊り大会 | 2026-07-25 to 2026-07-26 at `ven_579acb5cd30208dc` | official neighborhood association schedule confirms current-year dates; local listing supplies venue and times |
