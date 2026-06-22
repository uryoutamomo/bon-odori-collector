# Master RDB -> Notion sync dry-run

- generated_at: 2026-06-21T06:56:19.724747+00:00
- mode: dry_run
- master_db: `/tmp/ph2_apply_test.sqlite`
- selected_jobs: 1
- ready_jobs: 1
- skipped_jobs: 0
- applied_jobs: 0
- issues_by_severity: {}

## Apply Sequence

1. RDB apply only: `python3 dry_run_ph2_event_occurrence_apply.py --apply --event-name '品川区民まつり 荏原第一地区' --confirm 'APPLY PH2 EVENT OCCURRENCE'`
2. Notion sync only after review: `python3 sync_master_to_notion.py --requested-by dry_run_ph2_event_occurrence_apply.py --apply --confirm 'APPLY RDB TO NOTION'`

Both steps require separate review and explicit approval before running against production inputs.

| job | event | date | status | venue | page | result |
| --- | --- | --- | --- | --- | --- | --- |
| nsj_9f1e9140663ba631 | 品川区民まつり 荏原第一地区 | 2026-10-10 | 確認済み | 小山台小学校 | 37b8be04-e762-817f-aa8c-e3b49df8d530 | ready |

## Field Diffs

### 品川区民まつり 荏原第一地区

- job: `nsj_9f1e9140663ba631`
- Notion last edited: 2026-06-10T13:12:00.000Z
- job requested at: 2026-06-21T06:56:10.284434+00:00

| field | current Notion snapshot | proposed | changed |
| --- | --- | --- | --- |
| 開催日 |  | 2026-10-10 | True |
| 終了日 |  |  | False |
| 状態 | 未確認 | 確認済み | True |
| 情報源URL | https://www.city.shinagawa.tokyo.jp/PC/shisetsu/shisetsu-kuyakusyo/shisetsu-kuyakusyo-chiiki/hpg000017088.html | https://www.city.shinagawa.tokyo.jp/PC/shisetsu/shisetsu-kuyakusyo/shisetsu-kuyakusyo-chiiki/hpg000017088.html | False |
| 会場 | 小山台小学校 | 小山台小学校 | False |
| 会場ページID | 3718be04-e762-815c-9681-e985b9e2fc4d | 3718be04-e762-815c-9681-e985b9e2fc4d | False |
