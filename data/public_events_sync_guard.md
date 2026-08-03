# Public events sync guard

**Note**: This guard checks for blocking diffs only. Guard status `pass` means no blocking issues remain, but is NOT a deploy approval. Deploy decisions require explicit confirmation from the operator.

- generated_at: 2026-08-03T15:49:55.022455+00:00
- scope: read_only_public_sync_guard_no_writes
- status: pass
- safe_to_wholesale_sync: True
- public_deploy_requires_separate_approval: True
- deploy_approval_note: Guard pass only means no blocking public sync diffs remain. Public deploy still requires separate operator approval.
- failures: []
- warnings: ['master_rdb_newer_than_publication_gap_review']
- procedure_warnings: ['master_rdb_newer_than_publication_gap_review']

## Procedure Warnings

These warnings mean the public-event publication flow may have skipped a review step. They do not automatically approve or reject deploys; they should be resolved or consciously accepted before syncing/deploying.

- master_rdb_newer_than_publication_gap_review

## Raw Collector vs Site

- collector_event_count: 308
- site_event_count: 288
- collector_only_count: 20
- site_only_count: 0
- high_risk_diff_record_count: 29
- high_risk_event_count: 23
- records_by_family: {'historical_slide': 23, 'date_prediction': 6}
- records_by_action: {'individual_review': 23, 'low_priority_or_unclassified': 6}
- events_by_action: {'ended_transition_downgrade': 23}

## After Required Public Postprocessors

- collector_event_count: 308
- site_event_count: 288
- collector_only_count: 20
- site_only_count: 0
- high_risk_diff_record_count: 29
- high_risk_event_count: 23
- records_by_family: {'historical_slide': 23, 'date_prediction': 6}
- records_by_action: {'individual_review': 23, 'low_priority_or_unclassified': 6}
- events_by_action: {'ended_transition_downgrade': 23}

## Reviewed Exact Approvals

- schema: public_sync_exact_approvals_v1
- status: pass
- approval_count: 167
- status_counts: {'already_synced': 118, 'inactive': 7, 'already_applied': 22, 'applied': 20}
- failure_count: 0

## After Reviewed Exact Approvals

- collector_event_count: 308
- site_event_count: 308
- collector_only_count: 0
- site_only_count: 0
- high_risk_diff_record_count: 29
- high_risk_event_count: 23
- records_by_family: {'historical_slide': 23, 'date_prediction': 6}
- records_by_action: {'individual_review': 23, 'low_priority_or_unclassified': 6}
- events_by_action: {'ended_transition_downgrade': 23}

## Automatically Allowed Ended Transitions

- count: 23

| event | venue | ended on |
| --- | --- | --- |
| お花茶屋ふるさとまつり | お花茶屋公園 | 2026-08-03 |
| ふるさと和泉 みんなの夏祭り | 杉並和泉学園校庭 | 2026-08-01 |
| 上谷中町自治会 納涼盆踊り大会 | しょうぶ沼公園 | 2026-08-03 |
| 中央本町若松町会 盆踊り大会 | 若松公園 | 2026-08-01 |
| 中川納涼大盆踊り大会 | 都立中川公園ふれあい広場 | 2026-08-02 |
| 扇一丁目寺地明和会 盆踊り | 扇南公園 | 2026-08-02 |
| 扇南町会 盆踊り | 三嶋神社 | 2026-08-02 |
| 普賢寺自治会 納涼盆踊り大会 | 北野公園 | 2026-07-25 |
| 本木北町みのり町会 盆踊り | 田中稲荷神社 | 2026-07-26 |
| 東京ソラマチ夏まつり・墨田区民納涼民踊大会 | 東京スカイツリータウン ソラマチひろば | 2026-08-03 |
| 東和一丁目自治会 納涼盆踊り大会 | 西沼公園 | 2026-07-19 |
| 東和二丁目自治会・東和二丁目西自治会 納涼盆踊り大会 | 第六天公園 | 2026-07-26 |
| 東淵江自治会 納涼盆踊り大会 | 稗田公園 | 2026-07-11 |
| 梅田本町自治会 納涼盆踊り | 梅田南公園 | 2026-08-01 |
| 梅田正和町会 納涼盆踊り | 関原中央公園 | 2026-07-18 |
| 梅里中央公園盆おどり | 梅里中央公園 | 2026-08-01 |
| 綾瀬五・六丁目自治会 納涼盆踊り大会 | 東綾瀬公園 | 2026-07-19 |
| 綾瀬東町会 納涼盆踊り大会 | 蛭沼公園 | 2026-08-01 |
| 綾瀬自治会 納涼盆踊り大会 | 伊藤谷公園 | 2026-07-26 |
| 興野町会 盆踊り | 興野神社 | 2026-08-02 |
| 蒲原自治会 納涼盆踊り大会 | 宮元公園 | 2026-07-26 |
| 西武井荻商店街 納涼盆踊り大会 | 第一生命向い駐車場 | 2026-07-24 |
| 高井戸ちびっ子ぼんおどり | 高井戸地域区民センター広場 | 2026-07-30 |

## Blocking Examples

| action | event | venue | families | fields |
| --- | --- | --- | --- | ---: |
