# 日次X収穫サマリ

- 生成時刻: 2026-07-11T13:33:37.476072+00:00
- 対象期間: 直近 3 日
- 対象voices: 760件
- 候補総数: 120件

## 内訳
- 曲×会場共起: 15件
- 曲候補: 97件
- 用語候補: 8件

## レビュー対象
- 用語・共起レビュー: 23件
- 曲候補レビュー: 0件
- 曲の明白候補 dry-run: 86件
- 曲ノイズ除外: 11件

## 生成物
- non_song_json: `data/weekly_harvest_review_candidates.json`
- non_song_ui: `data/weekly_harvest_review_ui.html`
- song_json: `data/weekly_song_candidates_review.json`
- song_ui: `data/weekly_song_candidates_review_ui.html`

## 反映コマンド
- `python apply_weekly_song_review_decisions.py --dry-run`
- `python apply_weekly_harvest_human13_decisions.py --candidates data/weekly_harvest_review_candidates.json --decisions data/weekly_harvest_review_decisions.json --out data/weekly_harvest_apply_result.json --dry-run`

## 用語・共起レビュー例
- ダンシングヒーロー × 大正大学
- 万博音頭 × 大正大学
- あっぱれ音頭 × 大正大学
- あるいは踊り × 靖国神社
- よさこいまた踊り × 大正大学
- 交野節 × 大正大学
- 人と地域がつながる季節 × 大正大学
- 仏像音頭 × 大正大学
- 恵聖さん生唄の種物音頭 × 大正大学
- 本番前最後の踊り × 大正大学
- 東京音頭 × 大正大学
- 江州音頭 × 隅田公園
