# Master RDB -> Notion sync dry-run

- generated_at: 2026-06-22T14:04:00.226857+00:00
- mode: dry_run
- master_db: `data/bon_odori_master.sqlite`
- selected_jobs: 8
- ready_jobs: 0
- skipped_jobs: 8
- applied_jobs: 0
- issues_by_severity: {'medium': 8}

## Apply Sequence

1. RDB apply only: `python3 dry_run_ph2_event_occurrence_apply.py --apply --event-name '<reviewed event name>' --confirm 'APPLY PH2 EVENT OCCURRENCE'`
2. Refresh Notion snapshot immediately before Notion apply: `python3 build_notion_rdb.py`
3. Notion sync only after review: `python3 sync_master_to_notion.py --requested-by dry_run_ph2_event_occurrence_apply.py --apply --confirm 'APPLY RDB TO NOTION'`

Both apply steps require separate review and explicit approval before running against production inputs.
The snapshot refresh is mandatory because drift detection uses `data/notion_snapshot.sqlite`.

| job | target | date | status | venue | page | result |
| --- | --- | --- | --- | --- | --- | --- |
| nsj_570669415c22a2d5 | 歌舞伎町BON ODORI | 2026-08-15 | predicted | 歌舞伎町シネシティ広場 |  | prediction_review_only |
| nsj_5a96718435cedd20 | 第15回 鴨台盆踊り | 2026-07-04 | predicted | 大正大学 |  | prediction_review_only |
| nsj_849055fd5e6248ed | シタマチ.ふるさと盆踊り大会 | 2026-08-15 | predicted | おかちまちパンダ広場（御徒町駅南口駅前広場） |  | prediction_review_only |
| nsj_9e1da3d52f1f5167 | 西久保八幡神社 盆踊り | 2026-08-08 | predicted | 西久保八幡神社 |  | prediction_review_only |
| nsj_d6a3faab9e5ac051 | 赤坂浄土寺盆踊り大会 | 2026-07-26 | predicted | 浄土寺 |  | prediction_review_only |
| nsj_df9086558cbc8cd0 | 謝恩納涼盆踊り大会（青山善光寺） | 2026-07-27 | predicted | 青山善光寺 |  | prediction_review_only |
| nsj_e17c17509984fccf | 丸の内de盆踊り | 2026-07-31 | predicted | 行幸通り |  | prediction_review_only |
| nsj_f7bb3c4ab1f9c0dd | 自由が丘納涼盆踊り大会 | 2026-07-18 | predicted | 自由が丘駅前ロータリー 特設会場 |  | prediction_review_only |

## Issues

- medium predicted_occurrence_date_jobs_are_review_only: {'severity': 'medium', 'issue_type': 'predicted_occurrence_date_jobs_are_review_only', 'detail': 'sync_master_to_notion does not create predicted Notion events directly', 'job_id': 'nsj_570669415c22a2d5'}
- medium predicted_occurrence_date_jobs_are_review_only: {'severity': 'medium', 'issue_type': 'predicted_occurrence_date_jobs_are_review_only', 'detail': 'sync_master_to_notion does not create predicted Notion events directly', 'job_id': 'nsj_5a96718435cedd20'}
- medium predicted_occurrence_date_jobs_are_review_only: {'severity': 'medium', 'issue_type': 'predicted_occurrence_date_jobs_are_review_only', 'detail': 'sync_master_to_notion does not create predicted Notion events directly', 'job_id': 'nsj_849055fd5e6248ed'}
- medium predicted_occurrence_date_jobs_are_review_only: {'severity': 'medium', 'issue_type': 'predicted_occurrence_date_jobs_are_review_only', 'detail': 'sync_master_to_notion does not create predicted Notion events directly', 'job_id': 'nsj_9e1da3d52f1f5167'}
- medium predicted_occurrence_date_jobs_are_review_only: {'severity': 'medium', 'issue_type': 'predicted_occurrence_date_jobs_are_review_only', 'detail': 'sync_master_to_notion does not create predicted Notion events directly', 'job_id': 'nsj_d6a3faab9e5ac051'}
- medium predicted_occurrence_date_jobs_are_review_only: {'severity': 'medium', 'issue_type': 'predicted_occurrence_date_jobs_are_review_only', 'detail': 'sync_master_to_notion does not create predicted Notion events directly', 'job_id': 'nsj_df9086558cbc8cd0'}
- medium predicted_occurrence_date_jobs_are_review_only: {'severity': 'medium', 'issue_type': 'predicted_occurrence_date_jobs_are_review_only', 'detail': 'sync_master_to_notion does not create predicted Notion events directly', 'job_id': 'nsj_e17c17509984fccf'}
- medium predicted_occurrence_date_jobs_are_review_only: {'severity': 'medium', 'issue_type': 'predicted_occurrence_date_jobs_are_review_only', 'detail': 'sync_master_to_notion does not create predicted Notion events directly', 'job_id': 'nsj_f7bb3c4ab1f9c0dd'}

## Field Diffs

### 歌舞伎町BON ODORI

- job: `nsj_570669415c22a2d5`
- Notion last edited:
- job requested at: 2026-06-22T01:21:59.620223+00:00

| field | current Notion snapshot | proposed | changed |
| --- | --- | --- | --- |
| 開催日 |  | 2026-08-15 | True |
| 終了日 |  | 2026-08-15 | True |
| 状態 |  | predicted | True |
| 予測根拠 |  | 8月第3土曜 | True |
| 会場候補 |  | 歌舞伎町シネシティ広場 | True |

### 第15回 鴨台盆踊り

- job: `nsj_5a96718435cedd20`
- Notion last edited:
- job requested at: 2026-06-22T01:21:59.620223+00:00

| field | current Notion snapshot | proposed | changed |
| --- | --- | --- | --- |
| 開催日 |  | 2026-07-04 | True |
| 終了日 |  | 2026-07-05 | True |
| 状態 |  | predicted | True |
| 予測根拠 |  | 7月6日前後の週末 | True |
| 会場候補 |  | 大正大学 | True |

### シタマチ.ふるさと盆踊り大会

- job: `nsj_849055fd5e6248ed`
- Notion last edited:
- job requested at: 2026-06-22T01:21:59.620223+00:00

| field | current Notion snapshot | proposed | changed |
| --- | --- | --- | --- |
| 開催日 |  | 2026-08-15 | True |
| 終了日 |  | 2026-08-15 | True |
| 状態 |  | predicted | True |
| 予測根拠 |  | 8月第3土曜 | True |
| 会場候補 |  | おかちまちパンダ広場（御徒町駅南口駅前広場） | True |

### 西久保八幡神社 盆踊り

- job: `nsj_9e1da3d52f1f5167`
- Notion last edited:
- job requested at: 2026-06-22T01:21:59.620223+00:00

| field | current Notion snapshot | proposed | changed |
| --- | --- | --- | --- |
| 開催日 |  | 2026-08-08 | True |
| 終了日 |  | 2026-08-08 | True |
| 状態 |  | predicted | True |
| 予測根拠 |  | 8月9日前後の週末 | True |
| 会場候補 |  | 西久保八幡神社 | True |

### 赤坂浄土寺盆踊り大会

- job: `nsj_d6a3faab9e5ac051`
- Notion last edited:
- job requested at: 2026-06-22T01:21:59.620223+00:00

| field | current Notion snapshot | proposed | changed |
| --- | --- | --- | --- |
| 開催日 |  | 2026-07-26 | True |
| 終了日 |  | 2026-07-27 | True |
| 状態 |  | predicted | True |
| 予測根拠 |  | 7月26日前後 | True |
| 会場候補 |  | 浄土寺 | True |

### 謝恩納涼盆踊り大会（青山善光寺）

- job: `nsj_df9086558cbc8cd0`
- Notion last edited:
- job requested at: 2026-06-22T01:21:59.620223+00:00

| field | current Notion snapshot | proposed | changed |
| --- | --- | --- | --- |
| 開催日 |  | 2026-07-27 | True |
| 終了日 |  | 2026-07-27 | True |
| 状態 |  | predicted | True |
| 予測根拠 |  | 7月の最終月曜 | True |
| 会場候補 |  | 青山善光寺 | True |

### 丸の内de盆踊り

- job: `nsj_e17c17509984fccf`
- Notion last edited:
- job requested at: 2026-06-22T01:21:59.620223+00:00

| field | current Notion snapshot | proposed | changed |
| --- | --- | --- | --- |
| 開催日 |  | 2026-07-31 | True |
| 終了日 |  | 2026-07-31 | True |
| 状態 |  | predicted | True |
| 予測根拠 |  | 7月の最終金曜 | True |
| 会場候補 |  | 行幸通り | True |

### 自由が丘納涼盆踊り大会

- job: `nsj_f7bb3c4ab1f9c0dd`
- Notion last edited:
- job requested at: 2026-06-22T01:21:59.620223+00:00

| field | current Notion snapshot | proposed | changed |
| --- | --- | --- | --- |
| 開催日 |  | 2026-07-18 | True |
| 終了日 |  | 2026-07-20 | True |
| 状態 |  | predicted | True |
| 予測根拠 |  | 7月16日前後の土曜 | True |
| 会場候補 |  | 自由が丘駅前ロータリー 特設会場 | True |
