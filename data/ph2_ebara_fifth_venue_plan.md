# Ph2 Ebara fifth venue-change plan

- generated_at: 2026-06-21T08:31:31.129432+00:00
- mode: dry_run_copied_sqlite_only
- master_db: `data/bon_odori_master.sqlite`
- dry_run_db: `data/ph2_ebara_fifth_venue_plan.sqlite`
- issues_by_severity: {}

## Source Evidence

- event: 品川区民まつり 荏原第五地区
- official date: 2026-07-18 to 2026-07-19
- official venue: 杜松ホーム (東京都品川区豊町4-24-15)
- source: https://www.city.shinagawa.tokyo.jp/PC/shisetsu/shisetsu-kuyakusyo/shisetsu-kuyakusyo-chiiki/hpg000017088.html

## RDB Dry-Run Changes

| target | before | after |
| --- | --- | --- |
| venue | 旧杜松小学校 (東京都品川区豊町4-22-15) | 杜松ホーム (東京都品川区豊町4-24-15) |
| date |  to  / unknown | 2026-07-18 to 2026-07-19 / confirmed |

## New Venue

- venue_id: `ven_a2ba81d51cea787c`
- canonical_name: 杜松ホーム
- address: 東京都品川区豊町4-24-15
- latitude/longitude: 35.605442, 139.722931
- geocode source: GSI AddressSearch (東京都品川区豊町四丁目２４番１５号)
- old venue is preserved; this is not an alias of 旧杜松小学校.

## Notion Write-Back

- skipped: this plan is RDB-primary and does not create or update Notion pages.
- Notion remains a legacy/read-only reference unless a separate manual migration decision is made.

## Public Export Follow-Up

- After RDB apply, regenerate local public JSON from the master RDB and review the site diff before deploy.
- Public deploy remains a separate Uchida-san approval step.

## Apply Sequence Proposal

1. Review this dry-run plan with こと and 内田さん.
2. RDB apply only: add 杜松ホーム, preserve 旧杜松小学校, update 荏原第五地区 occurrence.
3. Regenerate local public JSON from the master RDB and review collector/site diffs.
4. Deploy only after a separate public-site approval.
