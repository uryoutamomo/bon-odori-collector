# 日次X収穫サマリ

- 生成時刻: 2026-07-12T08:33:59.637328+00:00
- 対象期間: 直近 3 日
- 対象voices: 1008件
- 候補総数: 139件

## 内訳
- 曲×会場共起: 17件
- 曲候補: 114件
- 用語候補: 8件

## レビュー対象
- 用語・共起レビュー: 25件
- 曲候補レビュー: 1件
- 曲の明白候補 dry-run: 98件
- 曲ノイズ除外: 15件

## 生成物
- non_song_json: `data/weekly_harvest_review_candidates.json`
- non_song_ui: `data/weekly_harvest_review_ui.html`
- song_json: `data/weekly_song_candidates_review.json`
- song_ui: `data/weekly_song_candidates_review_ui.html`

## 反映コマンド
- `python apply_weekly_song_review_decisions.py --dry-run`
- `python apply_weekly_harvest_human13_decisions.py --candidates data/weekly_harvest_review_candidates.json --decisions data/weekly_harvest_review_decisions.json --out data/weekly_harvest_apply_result.json --dry-run`

## 用語・共起レビュー例
- 東京五輪音頭 × 晴海ふ頭公園
- ダンシングヒーロー × 大正大学
- 万博音頭 × 大正大学
- あっぱれ音頭 × 大正大学
- おしりたんてい音頭 × 晴海ふ頭公園
- よさこいまた踊り × 大正大学
- を初めて踊り × 晴海ふ頭公園
- パンフレット掲載の踊り × 晴海ふ頭公園
- 交野節 × 大正大学
- 人と地域がつながる季節 × 大正大学
- 仏像音頭 × 大正大学
- 恵聖さん生唄の種物音頭 × 大正大学

## 曲レビュー例
- 郡上おどり
