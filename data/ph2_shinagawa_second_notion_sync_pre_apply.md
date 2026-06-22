# Master RDB -> Notion sync dry-run

- generated_at: 2026-06-21T07:30:00.493515+00:00
- mode: dry_run
- master_db: `data/bon_odori_master.sqlite`
- selected_jobs: 1
- ready_jobs: 1
- skipped_jobs: 0
- applied_jobs: 0
- issues_by_severity: {}

## Apply Sequence

1. RDB apply only: `python3 dry_run_ph2_event_occurrence_apply.py --apply --event-name '品川区民まつり 品川第二地区' --confirm 'APPLY PH2 EVENT OCCURRENCE'`
2. Refresh Notion snapshot immediately before Notion apply: `python3 build_notion_rdb.py`
3. Notion sync only after review: `python3 sync_master_to_notion.py --requested-by dry_run_ph2_event_occurrence_apply.py --apply --confirm 'APPLY RDB TO NOTION'`

Both apply steps require separate review and explicit approval before running against production inputs.
The snapshot refresh is mandatory because drift detection uses `data/notion_snapshot.sqlite`.

| job | event | date | status | venue | page | result |
| --- | --- | --- | --- | --- | --- | --- |
| nsj_054ac71c5ec10d2b | 品川区民まつり 品川第二地区 | 2026-07-25 | 確認済み | 天妙国寺 | 37b8be04-e762-8139-aa26-f7c1ae0a9ae6 | ready |

## Field Diffs

### 品川区民まつり 品川第二地区

- job: `nsj_054ac71c5ec10d2b`
- Notion last edited: 2026-06-10T13:12:00.000Z
- job requested at: 2026-06-21T07:29:02.020898+00:00

| field | current Notion snapshot | proposed | changed |
| --- | --- | --- | --- |
| 開催日 |  | 2026-07-25 | True |
| 終了日 |  | 2026-07-26 | True |
| 状態 | 未確認 | 確認済み | True |
| 情報源URL | https://www.city.shinagawa.tokyo.jp/PC/shisetsu/shisetsu-kuyakusyo/shisetsu-kuyakusyo-chiiki/hpg000017088.html | https://www.city.shinagawa.tokyo.jp/PC/shisetsu/shisetsu-kuyakusyo/shisetsu-kuyakusyo-chiiki/hpg000017088.html | False |
| 会場 | 城南小学校 | 天妙国寺 | True |
| 会場ページID | 3718be04-e762-8172-aa0d-c778081d41a0 | 3718be04-e762-816e-b1c0-ed3e65521bcb | True |

