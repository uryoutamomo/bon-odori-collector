# 日次X収穫サマリ

- 生成時刻: 2026-07-11T08:17:34.210270+00:00
- 対象期間: 直近 3 日
- 対象voices: 531件
- 候補総数: 89件

## 内訳
- 曲×会場共起: 9件
- 曲候補: 74件
- 用語候補: 6件

## レビュー対象
- 用語・共起レビュー: 15件
- 曲候補レビュー: 0件
- 曲の明白候補 dry-run: 65件
- 曲ノイズ除外: 9件

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
- あっぱれ音頭 × 大正大学
- あるいは踊り × 靖国神社
- よさこいまた踊り × 大正大学
- 恵聖さん生唄の種物音頭 × 大正大学
- 本番前最後の踊り × 大正大学
- 江州音頭 × 隅田公園
- 河内おとこ節 × 浄土寺
- 腕光らせて踊り × 晴海ふ頭公園
- 練習会
- 踊り会
- 参戦
