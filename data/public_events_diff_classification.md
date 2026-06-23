# Public events diff classification

- generated_at: 2026-06-23T06:46:23.613247+00:00
- scope: read_only_diff_classification_no_writes
- collector_event_count: 183
- site_event_count: 183
- collector_only_count: 3
- site_only_count: 3
- high_risk_event_count: 29
- high_risk_diff_record_count: 115
- records_by_family: {'season_hint': 97, 'date_prediction': 14, 'historical_slide': 3, 'detail': 1}
- records_by_action: {'individual_review': 79, 'low_priority_or_unclassified': 11, 'restore_collector_from_site_or_reenable_export_postprocess': 25}
- events_by_action: {'individual_review': 27, 'restore_collector_from_site_or_reenable_export_postprocess': 2}

## Action Buckets

### restore_collector_from_site_or_reenable_export_postprocess

| event | venue | families | fields |
| --- | --- | --- | ---: |
| イベント名未確認（築地社会教育会館） | 築地社会教育会館 | date_prediction, season_hint | 6 |
| 根津神社 盆踊り（文京区） | 根津神社 | date_prediction, season_hint | 6 |

### individual_review

| event | venue | families | fields |
| --- | --- | --- | ---: |
| SHIBUYA MIYASHITA PARK BON DANCE | 宮下公園 | season_hint | 3 |
| すみだ公園の盆踊り（名称推定） | すみだ公園（隅田公園・墨田区側） | season_hint | 1 |
| アークヒルズ秋祭り 盆踊り | アーク・カラヤン広場（アークヒルズ） | season_hint | 1 |
| 上笄町会お祭り 盆踊り | 長谷寺（西麻布・麻布大観音） | season_hint | 4 |
| 上野盆踊り会（厚澄会） | 上野恩賜公園 | date_prediction, season_hint | 5 |
| 中之郷公園の盆踊り（名称推定） | 中之郷公園（中之郷児童遊園） | season_hint | 1 |
| 六本木天祖神社（龍土神明宮）例大祭 盆踊り | 六本木天祖神社 | season_hint | 4 |
| 品川区民まつり 八潮地区 | 八潮公園 | date_prediction, historical_slide, season_hint | 8 |
| 品川区民まつり 荏原第三地区 | 京陽小学校 | date_prediction, historical_slide, season_hint | 8 |
| 品川区民まつり 荏原第五地区 | 杜松ホーム | detail | 1 |
| 品川区民まつり 荏原第四地区 | 上神明小学校 | date_prediction, historical_slide, season_hint | 8 |
| 品川第二地区 区民まつり・品川青年会 盆踊り大会（天妙国寺） | 天妙国寺 | date_prediction, season_hint | 5 |
| 増上寺 地蔵尊盆踊り大会 | 増上寺（大殿前広場） | season_hint | 4 |
| 小網神社の盆踊り（名称推定） | 小網神社 | season_hint | 3 |
| 戸越八幡神社例大祭 盆踊り | 戸越八幡神社 | date_prediction, season_hint | 5 |
| 新宿中央公園夏祭り 納涼盆踊り大会 | 新宿中央公園 ファンモアタイム広場 | season_hint | 4 |
| 旗岡八幡神社例大祭 | 旗岡八幡神社 | season_hint | 4 |
| 本四三ツ目児童遊園の盆踊り（名称推定） | 本四三ツ目児童遊園（三つ目児童公園） | season_hint | 1 |
| 江東天祖神社の盆踊り（名称推定） | 江東天祖神社（亀戸天祖神社） | season_hint | 1 |
| 浜二納涼盆踊り大会 | 浜町公園 | season_hint | 3 |
| 濱町音頭盆踊り大会 | 浜町公園 | season_hint | 3 |
| 牛嶋神社祭礼 奉納踊り | 牛嶋神社 | date_prediction, season_hint | 5 |
| 盆踊 〜BONDO〜 | しながわ中央公園 | season_hint | 3 |
| 赤坂夏おどり（旧 赤坂盆踊り） | 赤坂サカス広場 | season_hint | 4 |
| 赤坂氷川祭 盆踊り大会 | 赤坂氷川神社 | date_prediction, season_hint | 5 |
| 飛鳥山夏祭り～お城で盆おどり大作戦～ | 飛鳥山公園 | season_hint | 4 |
| 麻布氷川神社例大祭 盆踊り | 麻布氷川神社 | date_prediction, season_hint | 5 |

## Field-Level Site Update Candidates

These collector-only fields may be copied to site after individual review, but their events may still have other mixed diffs.

| event | venue | field | collector | site |
| --- | --- | --- | --- | --- |

## Individual Review Details

| event | venue | field | side | collector | site |
| --- | --- | --- | --- | --- | --- |
| SHIBUYA MIYASHITA PARK BON DANCE | 宮下公園 | season_hint | both_different | {"display_tier": "season_hint", "label": "9月下旬", "confidence": "lowest", "basis": "例年の開催月・旬ヒント"} | {"display_tier": "season_hint", "label": "9月中旬", "confidence": "lowest", "basis": "例年の開催月・旬ヒント"} |
| SHIBUYA MIYASHITA PARK BON DANCE | 宮下公園 | season_hint_label | both_different | "9月下旬" | "9月中旬" |
| SHIBUYA MIYASHITA PARK BON DANCE | 宮下公園 | season_jun | both_different | {"9": "下旬"} | {"9": "中旬"} |
| すみだ公園の盆踊り（名称推定） | すみだ公園（隅田公園・墨田区側） | season_hint | both_different | {"display_tier": "season_hint", "label": "9月中旬", "confidence": "lowest", "basis": "例年の開催月・旬ヒント"} | {"display_tier": "season_hint", "label": "9月中旬", "confidence": "lowest", "basis": "例年の開催月・旬ヒント"} |
| アークヒルズ秋祭り 盆踊り | アーク・カラヤン広場（アークヒルズ） | season_hint | both_different | {"display_tier": "season_hint", "label": "9月中旬", "confidence": "lowest", "basis": "例年の開催月・旬ヒント"} | {"display_tier": "season_hint", "label": "9月中旬", "confidence": "lowest", "basis": "例年の開催月・旬ヒント"} |
| 上笄町会お祭り 盆踊り | 長谷寺（西麻布・麻布大観音） | season_hint | both_different | {"display_tier": "season_hint", "label": "3月中旬・9月中旬", "confidence": "lowest", "basis": "例年の開催月・旬ヒント"} | {"display_tier": "season_hint", "label": "9月中旬", "confidence": "lowest", "basis": "例年の開催月・旬ヒント"} |
| 上笄町会お祭り 盆踊り | 長谷寺（西麻布・麻布大観音） | season_hint_label | both_different | "3月中旬・9月中旬" | "9月中旬" |
| 上笄町会お祭り 盆踊り | 長谷寺（西麻布・麻布大観音） | season_jun | both_different | {"3": "中旬", "9": "中旬"} | {"9": "中旬"} |
| 上笄町会お祭り 盆踊り | 長谷寺（西麻布・麻布大観音） | season_months | both_different | [3, 9] | [9] |
| 上野盆踊り会（厚澄会） | 上野恩賜公園 | season_hint | both_different | {"display_tier": "season_hint", "label": "2月中旬", "confidence": "lowest", "basis": "例年の開催月・旬ヒント"} | {"display_tier": "season_hint", "label": "6月・7月・8月・10月", "confidence": "lowest", "basis": "例年の開催月・旬ヒント"} |
| 上野盆踊り会（厚澄会） | 上野恩賜公園 | season_hint_label | both_different | "2月中旬" | "6月・7月・8月・10月" |
| 上野盆踊り会（厚澄会） | 上野恩賜公園 | season_jun | both_different | {"2": "中旬"} | {} |
| 上野盆踊り会（厚澄会） | 上野恩賜公園 | season_months | both_different | [2] | [6, 7, 8, 10] |
| 中之郷公園の盆踊り（名称推定） | 中之郷公園（中之郷児童遊園） | season_hint | both_different | {"display_tier": "season_hint", "label": "9月中旬", "confidence": "lowest", "basis": "例年の開催月・旬ヒント"} | {"display_tier": "season_hint", "label": "9月中旬", "confidence": "lowest", "basis": "例年の開催月・旬ヒント"} |
| 六本木天祖神社（龍土神明宮）例大祭 盆踊り | 六本木天祖神社 | season_hint | both_different | {"display_tier": "season_hint", "label": "2月中旬・4月中旬・9月中旬", "confidence": "lowest", "basis": "例年の開催月・旬ヒント"} | {"display_tier": "season_hint", "label": "9月中旬", "confidence": "lowest", "basis": "例年の開催月・旬ヒント"} |
| 六本木天祖神社（龍土神明宮）例大祭 盆踊り | 六本木天祖神社 | season_hint_label | both_different | "2月中旬・4月中旬・9月中旬" | "9月中旬" |
| 六本木天祖神社（龍土神明宮）例大祭 盆踊り | 六本木天祖神社 | season_jun | both_different | {"2": "中旬", "4": "中旬", "9": "中旬"} | {"9": "中旬"} |
| 六本木天祖神社（龍土神明宮）例大祭 盆踊り | 六本木天祖神社 | season_months | both_different | [2, 4, 9] | [9] |
| 品川区民まつり 八潮地区 | 八潮公園 | display_tier | both_different | "confirmed" | "season_hint" |
| 品川区民まつり 八潮地区 | 八潮公園 | recurrence_score | both_different | 0.95 | 0.25 |
| 品川区民まつり 荏原第三地区 | 京陽小学校 | display_tier | both_different | "confirmed" | "season_hint" |
| 品川区民まつり 荏原第三地区 | 京陽小学校 | recurrence_score | both_different | 0.95 | 0.25 |
| 品川区民まつり 荏原第五地区 | 杜松ホーム | detail | both_different | "2025-08-23 開催実績。2025 8/23 - 24。「品川区民まつり 荏原第五地区」8月23日(土)-24日(日)。 23日(土) 16:00-19:30。 24日(日) 16:00-18:30。 「模擬店・盆踊り・子どもコーナー・ステージ発表 ほか」。 踊りの時間詳細不明。" | "2026年公式情報: 2026-07-18〜2026-07-19、会場 杜松ホーム（東京都品川区豊町4-24-15）。" |
| 品川区民まつり 荏原第四地区 | 上神明小学校 | display_tier | both_different | "confirmed" | "season_hint" |
| 品川区民まつり 荏原第四地区 | 上神明小学校 | recurrence_score | both_different | 0.95 | 0.25 |
| 品川第二地区 区民まつり・品川青年会 盆踊り大会（天妙国寺） | 天妙国寺 | season_hint | both_different | {"display_tier": "season_hint", "label": "1月中旬・2月中旬・7月下旬・8月中旬", "confidence": "lowest", "basis": "例年の開催月・旬ヒント"} | {"display_tier": "season_hint", "label": "7月下旬", "confidence": "lowest", "basis": "例年の開催月・旬ヒント"} |
| 品川第二地区 区民まつり・品川青年会 盆踊り大会（天妙国寺） | 天妙国寺 | season_hint_label | both_different | "1月中旬・2月中旬・7月下旬・8月中旬" | "7月下旬" |
| 品川第二地区 区民まつり・品川青年会 盆踊り大会（天妙国寺） | 天妙国寺 | season_jun | both_different | {"7": "下旬", "1": "中旬", "2": "中旬", "8": "中旬"} | {"7": "下旬"} |
| 品川第二地区 区民まつり・品川青年会 盆踊り大会（天妙国寺） | 天妙国寺 | season_months | both_different | [1, 2, 7, 8] | [7] |
| 増上寺 地蔵尊盆踊り大会 | 増上寺（大殿前広場） | season_hint | both_different | {"display_tier": "season_hint", "label": "2月中旬・7月中旬", "confidence": "lowest", "basis": "例年の開催月・旬ヒント"} | {"display_tier": "season_hint", "label": "7月中旬", "confidence": "lowest", "basis": "例年の開催月・旬ヒント"} |
| 増上寺 地蔵尊盆踊り大会 | 増上寺（大殿前広場） | season_hint_label | both_different | "2月中旬・7月中旬" | "7月中旬" |
| 増上寺 地蔵尊盆踊り大会 | 増上寺（大殿前広場） | season_jun | both_different | {"7": "中旬", "2": "中旬"} | {"7": "中旬"} |
| 増上寺 地蔵尊盆踊り大会 | 増上寺（大殿前広場） | season_months | both_different | [2, 7] | [7] |
| 小網神社の盆踊り（名称推定） | 小網神社 | season_hint | both_different | {"display_tier": "season_hint", "label": "5月下旬", "confidence": "lowest", "basis": "例年の開催月・旬ヒント"} | {"display_tier": "season_hint", "label": "5月中旬", "confidence": "lowest", "basis": "例年の開催月・旬ヒント"} |
| 小網神社の盆踊り（名称推定） | 小網神社 | season_hint_label | both_different | "5月下旬" | "5月中旬" |
| 小網神社の盆踊り（名称推定） | 小網神社 | season_jun | both_different | {"5": "下旬"} | {"5": "中旬"} |
| 戸越八幡神社例大祭 盆踊り | 戸越八幡神社 | season_hint | both_different | {"display_tier": "season_hint", "label": "1月中旬・2月中旬・9月中旬・12月中旬", "confidence": "lowest", "basis": "例年の開催月・旬ヒント"} | {"display_tier": "season_hint", "label": "9月中旬", "confidence": "lowest", "basis": "例年の開催月・旬ヒント"} |
| 戸越八幡神社例大祭 盆踊り | 戸越八幡神社 | season_hint_label | both_different | "1月中旬・2月中旬・9月中旬・12月中旬" | "9月中旬" |
| 戸越八幡神社例大祭 盆踊り | 戸越八幡神社 | season_jun | both_different | {"9": "中旬", "1": "中旬", "2": "中旬", "12": "中旬"} | {"9": "中旬"} |
| 戸越八幡神社例大祭 盆踊り | 戸越八幡神社 | season_months | both_different | [1, 2, 9, 12] | [9] |
| 新宿中央公園夏祭り 納涼盆踊り大会 | 新宿中央公園 ファンモアタイム広場 | season_hint | both_different | {"display_tier": "season_hint", "label": "2月中旬・8月下旬", "confidence": "lowest", "basis": "例年の開催月・旬ヒント"} | {"display_tier": "season_hint", "label": "8月下旬", "confidence": "lowest", "basis": "例年の開催月・旬ヒント"} |
| 新宿中央公園夏祭り 納涼盆踊り大会 | 新宿中央公園 ファンモアタイム広場 | season_hint_label | both_different | "2月中旬・8月下旬" | "8月下旬" |
| 新宿中央公園夏祭り 納涼盆踊り大会 | 新宿中央公園 ファンモアタイム広場 | season_jun | both_different | {"2": "中旬", "8": "下旬"} | {"8": "下旬"} |
| 新宿中央公園夏祭り 納涼盆踊り大会 | 新宿中央公園 ファンモアタイム広場 | season_months | both_different | [2, 8] | [8] |
| 旗岡八幡神社例大祭 | 旗岡八幡神社 | season_hint | both_different | {"display_tier": "season_hint", "label": "2月中旬・8月中旬・9月下旬", "confidence": "lowest", "basis": "例年の開催月・旬ヒント"} | {"display_tier": "season_hint", "label": "9月中旬", "confidence": "lowest", "basis": "例年の開催月・旬ヒント"} |
| 旗岡八幡神社例大祭 | 旗岡八幡神社 | season_hint_label | both_different | "2月中旬・8月中旬・9月下旬" | "9月中旬" |
| 旗岡八幡神社例大祭 | 旗岡八幡神社 | season_jun | both_different | {"2": "中旬", "8": "中旬", "9": "下旬"} | {"9": "中旬"} |
| 旗岡八幡神社例大祭 | 旗岡八幡神社 | season_months | both_different | [2, 8, 9] | [9] |
| 本四三ツ目児童遊園の盆踊り（名称推定） | 本四三ツ目児童遊園（三つ目児童公園） | season_hint | both_different | {"display_tier": "season_hint", "label": "9月中旬", "confidence": "lowest", "basis": "例年の開催月・旬ヒント"} | {"display_tier": "season_hint", "label": "9月中旬", "confidence": "lowest", "basis": "例年の開催月・旬ヒント"} |
| 江東天祖神社の盆踊り（名称推定） | 江東天祖神社（亀戸天祖神社） | season_hint | both_different | {"display_tier": "season_hint", "label": "9月中旬", "confidence": "lowest", "basis": "例年の開催月・旬ヒント"} | {"display_tier": "season_hint", "label": "9月中旬", "confidence": "lowest", "basis": "例年の開催月・旬ヒント"} |
| 浜二納涼盆踊り大会 | 浜町公園 | season_hint | both_different | {"display_tier": "season_hint", "label": "9月中旬", "confidence": "lowest", "basis": "例年の開催月・旬ヒント"} | {"display_tier": "season_hint", "label": "9月上旬", "confidence": "lowest", "basis": "例年の開催月・旬ヒント"} |
| 浜二納涼盆踊り大会 | 浜町公園 | season_hint_label | both_different | "9月中旬" | "9月上旬" |
| 浜二納涼盆踊り大会 | 浜町公園 | season_jun | both_different | {"9": "中旬"} | {"9": "上旬"} |
| 濱町音頭盆踊り大会 | 浜町公園 | season_hint | both_different | {"display_tier": "season_hint", "label": "9月中旬", "confidence": "lowest", "basis": "例年の開催月・旬ヒント"} | {"display_tier": "season_hint", "label": "9月下旬", "confidence": "lowest", "basis": "例年の開催月・旬ヒント"} |
| 濱町音頭盆踊り大会 | 浜町公園 | season_hint_label | both_different | "9月中旬" | "9月下旬" |
| 濱町音頭盆踊り大会 | 浜町公園 | season_jun | both_different | {"9": "中旬"} | {"9": "下旬"} |
| 牛嶋神社祭礼 奉納踊り | 牛嶋神社 | season_hint | both_different | {"display_tier": "season_hint", "label": "1月中旬・2月中旬・9月中旬・12月中旬", "confidence": "lowest", "basis": "例年の開催月・旬ヒント"} | {"display_tier": "season_hint", "label": "9月中旬", "confidence": "lowest", "basis": "例年の開催月・旬ヒント"} |
| 牛嶋神社祭礼 奉納踊り | 牛嶋神社 | season_hint_label | both_different | "1月中旬・2月中旬・9月中旬・12月中旬" | "9月中旬" |
| 牛嶋神社祭礼 奉納踊り | 牛嶋神社 | season_jun | both_different | {"9": "中旬", "1": "中旬", "2": "中旬", "12": "中旬"} | {"9": "中旬"} |
| 牛嶋神社祭礼 奉納踊り | 牛嶋神社 | season_months | both_different | [1, 2, 9, 12] | [9] |
| 盆踊 〜BONDO〜 | しながわ中央公園 | season_hint | both_different | {"display_tier": "season_hint", "label": "5月下旬", "confidence": "lowest", "basis": "例年の開催月・旬ヒント"} | {"display_tier": "season_hint", "label": "5月中旬", "confidence": "lowest", "basis": "例年の開催月・旬ヒント"} |
| 盆踊 〜BONDO〜 | しながわ中央公園 | season_hint_label | both_different | "5月下旬" | "5月中旬" |
| 盆踊 〜BONDO〜 | しながわ中央公園 | season_jun | both_different | {"5": "下旬"} | {"5": "中旬"} |
| 赤坂夏おどり（旧 赤坂盆踊り） | 赤坂サカス広場 | season_hint | both_different | {"display_tier": "season_hint", "label": "2月中旬・8月下旬", "confidence": "lowest", "basis": "例年の開催月・旬ヒント"} | {"display_tier": "season_hint", "label": "8月下旬", "confidence": "lowest", "basis": "例年の開催月・旬ヒント"} |
| 赤坂夏おどり（旧 赤坂盆踊り） | 赤坂サカス広場 | season_hint_label | both_different | "2月中旬・8月下旬" | "8月下旬" |
| 赤坂夏おどり（旧 赤坂盆踊り） | 赤坂サカス広場 | season_jun | both_different | {"2": "中旬", "8": "下旬"} | {"8": "下旬"} |
| 赤坂夏おどり（旧 赤坂盆踊り） | 赤坂サカス広場 | season_months | both_different | [2, 8] | [8] |
| 赤坂氷川祭 盆踊り大会 | 赤坂氷川神社 | season_hint | both_different | {"display_tier": "season_hint", "label": "1月中旬・2月中旬・3月中旬・9月中旬", "confidence": "lowest", "basis": "例年の開催月・旬ヒント"} | {"display_tier": "season_hint", "label": "9月中旬", "confidence": "lowest", "basis": "例年の開催月・旬ヒント"} |
| 赤坂氷川祭 盆踊り大会 | 赤坂氷川神社 | season_hint_label | both_different | "1月中旬・2月中旬・3月中旬・9月中旬" | "9月中旬" |
| 赤坂氷川祭 盆踊り大会 | 赤坂氷川神社 | season_jun | both_different | {"9": "中旬", "1": "中旬", "2": "中旬", "3": "中旬"} | {"9": "中旬"} |
| 赤坂氷川祭 盆踊り大会 | 赤坂氷川神社 | season_months | both_different | [1, 2, 3, 9] | [9] |
| 飛鳥山夏祭り～お城で盆おどり大作戦～ | 飛鳥山公園 | season_hint | both_different | {"display_tier": "season_hint", "label": "1月中旬・2月中旬・8月中旬", "confidence": "lowest", "basis": "例年の開催月・旬ヒント"} | {"display_tier": "season_hint", "label": "8月中旬", "confidence": "lowest", "basis": "例年の開催月・旬ヒント"} |
| 飛鳥山夏祭り～お城で盆おどり大作戦～ | 飛鳥山公園 | season_hint_label | both_different | "1月中旬・2月中旬・8月中旬" | "8月中旬" |
| 飛鳥山夏祭り～お城で盆おどり大作戦～ | 飛鳥山公園 | season_jun | both_different | {"1": "中旬", "2": "中旬", "8": "中旬"} | {"8": "中旬"} |
| 飛鳥山夏祭り～お城で盆おどり大作戦～ | 飛鳥山公園 | season_months | both_different | [1, 2, 8] | [8] |
| 麻布氷川神社例大祭 盆踊り | 麻布氷川神社 | season_hint | both_different | {"display_tier": "season_hint", "label": "1月中旬・2月中旬・3月中旬・9月中旬・12月中旬", "confidence": "lowest", "basis": "例年の開催月・旬ヒント"} | {"display_tier": "season_hint", "label": "9月中旬", "confidence": "lowest", "basis": "例年の開催月・旬ヒント"} |
| 麻布氷川神社例大祭 盆踊り | 麻布氷川神社 | season_hint_label | both_different | "1月中旬・2月中旬・3月中旬・9月中旬・12月中旬" | "9月中旬" |
| 麻布氷川神社例大祭 盆踊り | 麻布氷川神社 | season_jun | both_different | {"9": "中旬", "1": "中旬", "2": "中旬", "3": "中旬", "12": "中旬"} | {"9": "中旬"} |
| 麻布氷川神社例大祭 盆踊り | 麻布氷川神社 | season_months | both_different | [1, 2, 3, 9, 12] | [9] |
