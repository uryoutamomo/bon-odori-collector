# Ph2 Ebara fifth RDB apply report

- generated_at: 2026-06-21T14:52:59.740731+00:00
- mode: apply
- target_db: `data/bon_odori_master.sqlite`
- dry_run_db: ``
- backup_db: `data/backups/bon_odori_master.20260621T145259.740731+0000.sqlite.bak`
- db_committed: True
- rolled_back: False
- issues_by_severity: {}
- audit_issues_by_severity: {'medium': 3}

## Change

| target | before | after |
| --- | --- | --- |
| venue | 旧杜松小学校 (東京都品川区豊町4-22-15) | 杜松ホーム (東京都品川区豊町4-24-15) |
| date |  to  / unknown | 2026-07-18 to 2026-07-19 / confirmed |
| confidence | unknown | high |

## New Venue

- venue_id: `ven_a2ba81d51cea787c`
- created_this_run: True
- name: 杜松ホーム
- address: 東京都品川区豊町4-24-15
- latitude/longitude: 35.605442, 139.722931
- geocode source: GSI AddressSearch (東京都品川区豊町四丁目２４番１５号)
- old venue is preserved; this is not an alias of 旧杜松小学校.

## Scope

- Notion write-back: skipped
- public JSON write: skipped
- next step: public export dry-run and collector/site diff review
