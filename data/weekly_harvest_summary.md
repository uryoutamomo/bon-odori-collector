# 日次X収穫サマリ

- 生成時刻: 2026-07-22T08:47:16.319022+00:00
- 対象期間: 直近 3 日
- 対象voices: 1084件
- 候補総数: 126件

## 内訳
- 曲×会場共起: 7件
- 曲候補: 113件
- 用語候補: 6件

## レビュー対象
- 用語・共起レビュー: 13件
- 曲候補レビュー: 2件
- 曲の明白候補 dry-run: 91件
- 曲ノイズ除外: 20件

## 生成物
- non_song_json: `data/weekly_harvest_review_candidates.json`
- non_song_ui: `data/weekly_harvest_review_ui.html`
- song_json: `data/weekly_song_candidates_review.json`
- song_ui: `data/weekly_song_candidates_review_ui.html`

## 反映コマンド
- `python apply_weekly_song_review_decisions.py --dry-run`
- `python apply_weekly_harvest_human13_decisions.py --candidates data/weekly_harvest_review_candidates.json --decisions data/weekly_harvest_review_decisions.json --out data/weekly_harvest_apply_result.json --dry-run`

## 用語・共起レビュー例
- おしりたんてい音頭 × 晴海ふ頭公園
- ダンシングヒーロー × 晴海ふ頭公園
- の出演や万博音頭 × 大正大学
- やぐらを囲む大きな踊り × 築地本願寺
- 根津藍染通り音頭 × 赤坂氷川神社
- 真室川音頭 × 浄土寺
- 赤坂小唄 × 浄土寺
- 練習会
- 踊り会
- ハシゴ
- はしご
- 梯子

## 曲レビュー例
- 郡上おどり
- 徳島市阿波おどり
