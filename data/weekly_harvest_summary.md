# 日次X収穫サマリ

- 生成時刻: 2026-07-14T08:30:29.588704+00:00
- 対象期間: 直近 3 日
- 対象voices: 1011件
- 候補総数: 139件

## 内訳
- 曲×会場共起: 25件
- 曲候補: 105件
- 用語候補: 9件

## レビュー対象
- 用語・共起レビュー: 34件
- 曲候補レビュー: 2件
- 曲の明白候補 dry-run: 84件
- 曲ノイズ除外: 19件

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
- らんまん踊り × 靖国神社
- 多くの踊り × 靖国神社
- 大東京音頭 × 靖国神社
- 東京音頭 × 靖国神社
- ダンシングヒーロー × 靖国神社
- 万博音頭 × 大正大学
- おしりたんてい音頭 × 晴海ふ頭公園
- その羽田節 × 羽田神社
- とした踊り × 晴海ふ頭公園
- を初めて踊り × 晴海ふ頭公園
- スッキリ音頭 × 羽田神社

## 曲レビュー例
- 郡上おどり
- 盆ジョビ
