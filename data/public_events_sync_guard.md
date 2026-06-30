# Public events sync guard

**Note**: This guard checks for blocking diffs only. Guard status `pass` means no blocking issues remain, but is NOT a deploy approval. Deploy decisions require explicit confirmation from the operator.

- generated_at: 2026-06-30T15:23:08.973742+00:00
- scope: read_only_public_sync_guard_no_writes
- status: block
- safe_to_wholesale_sync: False
- public_deploy_requires_separate_approval: True
- deploy_approval_note: Guard pass only means no blocking public sync diffs remain. Public deploy still requires separate operator approval.
- failures: ['individual_review_diffs_remain']
- warnings: []
- procedure_warnings: []

## Procedure Warnings

These warnings mean the public-event publication flow may have skipped a review step. They do not automatically approve or reject deploys; they should be resolved or consciously accepted before syncing/deploying.

- none

## Raw Collector vs Site

- collector_event_count: 185
- site_event_count: 185
- collector_only_count: 0
- site_only_count: 0
- high_risk_diff_record_count: 32
- high_risk_event_count: 32
- records_by_family: {'source': 32}
- records_by_action: {'individual_review': 32}
- events_by_action: {'individual_review': 32}

## After Required Public Postprocessors

- collector_event_count: 185
- site_event_count: 185
- collector_only_count: 0
- site_only_count: 0
- high_risk_diff_record_count: 32
- high_risk_event_count: 32
- records_by_family: {'source': 32}
- records_by_action: {'individual_review': 32}
- events_by_action: {'individual_review': 32}

## Blocking Examples

| action | event | venue | families | fields |
| --- | --- | --- | --- | ---: |
| individual_review | あずま通り商店街「下北沢盆踊り2025」 | 下北沢駅東口 | source | 1 |
| individual_review | 上北沢盆踊り実行委員会 「上北沢の納涼盆踊り」 | 上北沢小学校 | source | 1 |
| individual_review | 世田谷駅前商店街振興組合「納涼盆踊り大会」 | 円光院駐車場 | source | 1 |
| individual_review | 丸の内de盆踊り | 行幸通り | source | 1 |
| individual_review | 六本木ヒルズ盆踊り | 六本木ヒルズアリーナ | source | 1 |
| individual_review | 千歳台廻沢地区盆踊り | 廻沢稲荷神社 | source | 1 |
| individual_review | 喜多見盆踊り大会 | 小田急線喜多見駅前 南口広場 | source | 1 |
| individual_review | 大蔵本村睦会 「盆踊り大会」 | 大蔵氷川神社 | source | 1 |
| individual_review | 奥沢交和会 | 奥沢小学校 | source | 1 |
| individual_review | 宇奈根町会 盆踊り大会 | 宇奈根氷川神社 | source | 1 |
| individual_review | 山王音頭と民踊大会 | 山王パークタワー公開空地 | source | 1 |
| individual_review | 希望ヶ丘団地夏まつり | 希望ヶ丘団地 テニスコート | source | 1 |
| individual_review | 成城学園 盆踊り大会 | 成城大学9号館前広場 | source | 1 |
| individual_review | 新井町会連合会・中野通り桜まつり実行委員会「中野通り桜まつり」 | 新井薬師公園 | source | 1 |
| individual_review | 新町公民会 盆踊り大会 | 久富稲荷神社 | source | 1 |
| individual_review | 瀬田商店会 瀬田納涼盆踊り | 瀬田中学校 | source | 1 |
| individual_review | 玉川町会盆おどり大会 | 二子玉川西地区ふれあい広場(246高架下) | source | 1 |
| individual_review | 盆踊り(池尻地区) | 池尻稲荷神社 | source | 1 |
| individual_review | 砧町町会「納涼夏祭り大会」 | 三峰公園 | source | 1 |
| individual_review | 祖師谷商店街振興組合 | 小田急線祖師ヶ谷大蔵駅前広場 | source | 1 |
| individual_review | 祖師谷昇進会商店街(振)盆踊り | 祖師谷神明社 | source | 1 |
| individual_review | 納涼盆踊り大会 | 玉川中町公園 | source | 1 |
| individual_review | 納涼盆踊り大会 | 駒沢緑泉公園 | source | 1 |
| individual_review | 船橋会 盆踊り | 千歳船橋駅前広場 | source | 1 |
| individual_review | 芦花公園商店街振興組合 「芦花公園駅前盆踊り大会」 | 京王線芦花公園駅前ロータリー(南口) | source | 1 |
| individual_review | 葛飾菖蒲まつり 水元公園会場 民踊パレード | 水元公園内はなしょうぶ園口 | source | 1 |
| individual_review | 親子盆踊り大会 | 八幡小学校 | source | 1 |
| individual_review | 郡上おどり in 青山 | 秩父宮ラグビー場駐車場 | source | 1 |
| individual_review | 野毛町会 納涼盆踊り大会 | 野毛六所神社 | source | 1 |
| individual_review | 鎌田協和会 鎌田納涼盆踊り | 鎌田天神社 | source | 1 |
| individual_review | 馬込地区自治会連合会、馬籠商店会連合睦会 | 馬込桜並木公園、馬込桜並木通り | source | 1 |
| individual_review | 駒澤大学同窓会東京都支部・営友会 | 駒澤大学 駒沢キャンパス | source | 1 |
