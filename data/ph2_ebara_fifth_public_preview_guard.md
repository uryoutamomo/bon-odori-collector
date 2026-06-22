# Public events sync guard

- generated_at: 2026-06-21T14:53:43.318489+00:00
- scope: read_only_public_sync_guard_no_writes
- status: block
- safe_to_wholesale_sync: False
- failures: ['event_key_mismatch', 'individual_review_diffs_remain']
- warnings: ['raw_restore_candidates_resolved_by_required_postprocessors']

## Raw Collector vs Site

- collector_event_count: 182
- site_event_count: 182
- collector_only_count: 1
- site_only_count: 1
- high_risk_diff_record_count: 1639
- high_risk_event_count: 153
- records_by_family: {'historical_reference': 658, 'season_hint': 290, 'historical_slide': 681, 'detail_or_fixed_rule': 4, 'date_prediction': 6}
- records_by_action: {'restore_collector_from_site_or_reenable_export_postprocess': 1548, 'individual_review': 87, 'site_update_candidate_after_review': 4}
- events_by_action: {'restore_collector_from_site_or_reenable_export_postprocess': 76, 'individual_review': 77}

## After Required Public Postprocessors

- collector_event_count: 182
- site_event_count: 182
- collector_only_count: 1
- site_only_count: 1
- high_risk_diff_record_count: 175
- high_risk_event_count: 77
- records_by_family: {'historical_reference': 77, 'historical_slide': 88, 'detail_or_fixed_rule': 4, 'date_prediction': 6}
- records_by_action: {'individual_review': 163, 'site_update_candidate_after_review': 4, 'restore_collector_from_site_or_reenable_export_postprocess': 8}
- events_by_action: {'individual_review': 77}

## Blocking Examples

| action | event | venue | families | fields |
| --- | --- | --- | --- | ---: |
| individual_review | あずま通り商店街「下北沢盆踊り2025」 | 下北沢駅東口 | historical_reference, historical_slide | 2 |
| individual_review | 三角広場まつり「居酒屋盆踊り」 | 新宿住友ビル三角広場 | historical_reference, historical_slide | 2 |
| individual_review | 上北沢盆踊り実行委員会 「上北沢の納涼盆踊り」 | 上北沢小学校 | historical_reference, historical_slide | 2 |
| individual_review | 下代田東町会 「下代田東子供祭り・納涼祭り」 | 下代田児童遊園 | historical_reference, historical_slide | 2 |
| individual_review | 下落合四丁目町会 盆踊り大会 | 下落合公園 | historical_reference, historical_slide | 2 |
| individual_review | 下落合町会知久会 第9回盆踊り | 清水川橋公園 | historical_reference, historical_slide | 2 |
| individual_review | 世田谷駅前商店街振興組合「納涼盆踊り大会」 | 円光院駐車場 | historical_reference, historical_slide | 2 |
| individual_review | 中目黒盆踊り大会 | フナイリバ（目黒川船入場広場） | historical_reference, historical_slide | 2 |
| individual_review | 北新宿四丁目 盆踊り大会 | 北柏木公園 | historical_reference, historical_slide | 2 |
| individual_review | 北糀谷町会 「納涼踊り大会」 | 子安八幡神社 | historical_reference, historical_slide | 2 |
| individual_review | 千歳台廻沢地区盆踊り | 廻沢稲荷神社 | historical_reference, historical_slide | 2 |
| individual_review | 原町一丁目町会 天祖神社例大祭 盆踊り | 原町天祖神社 | historical_reference, historical_slide | 2 |
| individual_review | 向島一丁目 牛嶋神社 ミニ奉納踊り | 向島1丁目旧町会会館前 | historical_reference, historical_slide | 2 |
| individual_review | 品川区民まつり 西大井広場公園 盆踊り | 西大井広場公園 | historical_reference, historical_slide | 2 |
| individual_review | 喜多見盆踊り大会 | 小田急線喜多見駅前 南口広場 | historical_reference, historical_slide | 2 |
| individual_review | 地域のふれあい第37回盆踊り大会 | JR目黒駅西口前 | historical_reference, historical_slide | 2 |
| individual_review | 坂本町会 納涼祭 | さかもと朝顔広場（旧坂本小学校跡地） | historical_reference, historical_slide | 2 |
| individual_review | 堤方東町会「盆踊り大会」 | 池上第二小学校 | historical_reference, historical_slide | 2 |
| individual_review | 大森南一丁目自治会「納涼盆踊り大会」 | 大森南一丁目公園 | historical_reference, historical_slide | 2 |
| individual_review | 大蔵本村睦会 「盆踊り大会」 | 大蔵氷川神社 | historical_reference, historical_slide | 2 |
| individual_review | 大蔵東部町会「親子納涼盆踊り大会」 | 横根稲荷神社 | historical_reference, historical_slide | 2 |
| individual_review | 太平一丁目 牛嶋神社 奉納踊り | 報恩寺境内 | historical_reference, historical_slide | 2 |
| individual_review | 奥沢交和会 | 奥沢小学校 | historical_reference, historical_slide | 2 |
| individual_review | 宇奈根町会 盆踊り大会 | 宇奈根氷川神社 | historical_reference, historical_slide | 2 |
| individual_review | 山王音頭と民踊大会 | 山王パークタワー公開空地 | detail_or_fixed_rule | 2 |
| individual_review | 岡本自治会「盆踊り大会」 | 長円寺 | historical_reference, historical_slide | 2 |
| individual_review | 市野倉南町会 盆踊り | 市野倉南児童公園 | historical_reference, historical_slide | 2 |
| individual_review | 希望ヶ丘団地夏まつり | 希望ヶ丘団地 テニスコート | historical_reference, historical_slide | 2 |
| individual_review | 成城学園 盆踊り大会 | 成城大学9号館前広場 | historical_reference, historical_slide | 2 |
| individual_review | 戸越八幡神社例大祭 奉納盆踊り大会 | 豊町一丁目会館前 | historical_reference, historical_slide | 2 |
| individual_review | 押上三丁目伸成町会 飛木稲荷神社神幸大祭 祭礼踊り | 伸成町会会館前 路上 | historical_reference, historical_slide | 2 |
| individual_review | 新町公民会 盆踊り大会 | 久富稲荷神社 | historical_reference, historical_slide | 2 |
| individual_review | 旗の台稲荷通り商店会盆踊り 盆ROCK | 旗の台稲荷通り商店街 | historical_reference, historical_slide | 2 |
| individual_review | 東糀谷四・五・六町会 納涼盆踊り大会 | 旭児童遊園 | historical_reference, historical_slide | 2 |
| individual_review | 柏木地区6町会盆踊り大会 | 北新宿公園 | historical_reference, historical_slide | 2 |
| individual_review | 森ヶ崎自治会 | 大森南4丁目公園 | historical_reference, historical_slide | 2 |
| individual_review | 歌舞伎町BON ODORI | 歌舞伎町シネシティ広場 | date_prediction, historical_reference, historical_slide | 10 |
| individual_review | 法人格砧町自治会「納涼盆踊り大会」 | 砧八丁目児童遊園 | historical_reference, historical_slide | 2 |
| individual_review | 瀬田商店会 瀬田納涼盆踊り | 瀬田中学校 | historical_reference, historical_slide | 2 |
| individual_review | 玉川町会盆おどり大会 | 二子玉川西地区ふれあい広場(246高架下) | historical_reference, historical_slide | 2 |
