# Master RDB -> Notion sync dry-run

- generated_at: 2026-06-21T07:33:16.366963+00:00
- mode: apply
- master_db: `data/bon_odori_master.sqlite`
- selected_jobs: 1
- ready_jobs: 1
- skipped_jobs: 0
- applied_jobs: 1
- issues_by_severity: {}

## Apply Sequence

1. RDB venue review apply queues the venue sync job.
2. Refresh Notion snapshot immediately before Notion apply: `python3 build_notion_rdb.py`
3. Venue sync only after review: `python3 sync_master_to_notion.py --target-table venues --requested-by apply_ph2_shinagawa_second_venue_review.py --apply --confirm 'APPLY RDB TO NOTION'`

Both apply steps require separate review and explicit approval before running against production inputs.
The snapshot refresh is mandatory because drift detection uses `data/notion_snapshot.sqlite`.

| job | target | date | status | venue | page | result |
| --- | --- | --- | --- | --- | --- | --- |
| nsj_99eca1b76cdbc965 | 天妙国寺 |  |  | 天妙国寺 | 3718be04-e762-816e-b1c0-ed3e65521bcb | ready |

## Field Diffs

### 天妙国寺

- job: `nsj_99eca1b76cdbc965`
- Notion last edited: 2026-06-11T15:27:00.000Z
- job requested at: 2026-06-21T07:32:02.338175+00:00

| field | current Notion snapshot | proposed | changed |
| --- | --- | --- | --- |
| 住所 | 東京都品川区南品儑2-8-23 | 東京都品川区南品川2-8-23 | True |

