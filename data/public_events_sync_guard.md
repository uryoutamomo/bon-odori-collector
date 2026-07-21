# Public events sync guard

**Note**: This guard checks for blocking diffs only. Guard status `pass` means no blocking issues remain, but is NOT a deploy approval. Deploy decisions require explicit confirmation from the operator.

- generated_at: 2026-07-21T05:26:09.863206+00:00
- scope: read_only_public_sync_guard_no_writes
- status: block
- safe_to_wholesale_sync: False
- public_deploy_requires_separate_approval: True
- deploy_approval_note: Guard pass only means no blocking public sync diffs remain. Public deploy still requires separate operator approval.
- failures: ['event_key_mismatch', 'individual_review_diffs_remain']
- warnings: []
- procedure_warnings: []

## Procedure Warnings

These warnings mean the public-event publication flow may have skipped a review step. They do not automatically approve or reject deploys; they should be resolved or consciously accepted before syncing/deploying.

- none

## Raw Collector vs Site

- collector_event_count: 209
- site_event_count: 209
- collector_only_count: 2
- site_only_count: 2
- high_risk_diff_record_count: 81
- high_risk_event_count: 21
- records_by_family: {'historical_slide': 37, 'date_prediction': 38, 'historical_reference': 4, 'detail': 1, 'source': 1}
- records_by_action: {'individual_review': 27, 'low_priority_or_unclassified': 38, 'restore_collector_from_site_or_reenable_export_postprocess': 16}
- events_by_action: {'individual_review': 19, 'expired_historical_slide_downgrade': 2}

## After Required Public Postprocessors

- collector_event_count: 209
- site_event_count: 209
- collector_only_count: 2
- site_only_count: 2
- high_risk_diff_record_count: 81
- high_risk_event_count: 21
- records_by_family: {'historical_slide': 37, 'date_prediction': 38, 'historical_reference': 4, 'detail': 1, 'source': 1}
- records_by_action: {'individual_review': 27, 'low_priority_or_unclassified': 38, 'restore_collector_from_site_or_reenable_export_postprocess': 16}
- events_by_action: {'individual_review': 19, 'expired_historical_slide_downgrade': 2}

## Blocking Examples

| action | event | venue | families | fields |
| --- | --- | --- | --- | ---: |
| individual_review | TOKYO盆ダンス×STEAM FESTIVAL2026 | 上野恩賜公園 | date_prediction, historical_slide | 3 |
| individual_review | ふるさと東京応援祭 第三回ビールと浴衣de盆踊り in上野2026 | 上野恩賜公園 | date_prediction, historical_slide | 3 |
| individual_review | みたままつり 納涼民踊のつどい | 靖国神社 | date_prediction, historical_slide | 3 |
| individual_review | 三角広場まつり「居酒屋盆踊り」 | 新宿住友ビル三角広場 | date_prediction, historical_slide | 3 |
| individual_review | 佐竹ゲバゲバ盆踊り | 佐竹商店街アーケード下 | date_prediction, historical_slide | 3 |
| individual_review | 品川区民まつり 荏原第五地区 | 杜松ホーム | date_prediction, historical_slide | 3 |
| individual_review | 大和町八幡神社大盆踊り会 | 中野大和町八幡神社 | date_prediction, historical_slide | 3 |
| individual_review | 奥浅草盆踊り | 隅田公園 | date_prediction, historical_slide | 3 |
| individual_review | 新宿二丁目太宗寺盆踊り大会 | 太宗寺 | date_prediction, historical_slide | 3 |
| individual_review | 木場一・六町会 盆踊り大会 | 深川ギャザリアセンタープラザ | date_prediction, historical_slide | 3 |
| individual_review | 木場二丁目 盆踊り大会 | 木場二丁目公園 | date_prediction, historical_slide | 3 |
| individual_review | 柳ばし納涼盆おどり | 柳橋中央通り | date_prediction, historical_slide | 3 |
| individual_review | 神楽坂夏まつり 盆踊り in 神楽坂 | りそな銀行神楽坂支店前 | date_prediction, historical_slide | 3 |
| individual_review | 第26回 四谷納涼踊り大会 | 四谷ひろばグランド（旧四谷第四小） | date_prediction, historical_slide | 3 |
| individual_review | 第2回 晴海ふ頭公園盆踊り大会 | 晴海ふ頭公園 | date_prediction, historical_slide | 3 |
| individual_review | 第46回 巣鴨盆踊り大会 | 巣鴨駅南口ロータリー | date_prediction, historical_slide | 3 |
| individual_review | 自由が丘納涼盆踊り大会 | 自由が丘駅前ロータリー 特設会場 | date_prediction, detail, historical_slide, source | 5 |
| individual_review | 郡上おどり in 青山 | 秩父宮ラグビー場駐車場 | date_prediction, historical_slide | 3 |
| individual_review | 銀座一丁目東町会・新富町会 納涼盆踊り大会 | 京橋公園 | date_prediction, historical_slide | 3 |
