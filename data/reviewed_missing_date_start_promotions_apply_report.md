# Reviewed missing_date_start promotions

- generated_at: 2026-07-01T10:53:01.803237+00:00
- mode: apply
- target_db: `data/bon_odori_master.sqlite`
- dry_run_db: `data/reviewed_missing_date_start_promotions_dry_run.sqlite`
- backup_db: `data/backups/bon_odori_master.20260701T105301.803237+0000.sqlite.bak`
- db_committed: True
- applied_count: 1
- skipped_count: 2
- high_issue_count: 0

| event | date | venue | source | status |
| --- | --- | --- | --- | --- |
| 増上寺 地蔵尊盆踊り大会 | 2026-07-24 to 2026-07-25 | 増上寺（大殿前広場） | https://www.zojoji.or.jp/event/ev_bonodori.html | confirmed |

## Skipped

| event | reason |
| --- | --- |
| SHIBUYA MIYASHITA PARK BON DANCE | already_applied |
| 盆踊 〜BONDO〜 | already_applied |
