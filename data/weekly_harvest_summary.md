# 日次X収穫サマリ

- 生成時刻: 2026-07-31T09:34:15.670717+00:00
- 対象期間: 直近 3 日
- 対象voices: 3721件
- 候補総数: 243件

## 内訳
- 曲×会場共起: 30件
- 曲候補: 205件
- 用語候補: 8件

## レビュー対象
- 用語・共起レビュー: 38件
- 曲候補レビュー: 2件
- 曲の明白候補 dry-run: 159件
- 曲ノイズ除外: 44件

## 生成物
- non_song_json: `data/weekly_harvest_review_candidates.json`
- non_song_ui: `data/weekly_harvest_review_ui.html`
- song_json: `data/weekly_song_candidates_review.json`
- song_ui: `data/weekly_song_candidates_review_ui.html`

## 反映コマンド
- `python apply_weekly_song_review_decisions.py --dry-run`
- `python apply_weekly_harvest_human13_decisions.py --candidates data/weekly_harvest_review_candidates.json --decisions data/weekly_harvest_review_decisions.json --out data/weekly_harvest_apply_result.json --dry-run`

## 用語・共起レビュー例
- 大江戸助六音頭 × 築地本願寺
- 河内音頭 × 築地本願寺
- 築地音頭 × 築地本願寺
- 斎太郎節 × 築地本願寺
- 法輪音頭 × 築地本願寺
- あやめ踊り × 築地本願寺
- おしりたんてい音頭 × 晴海ふ頭公園
- ホームラン音頭 × 築地本願寺
- 東京音頭 × 築地本願寺
- 炭坑節 × 築地本願寺
- ダンシングヒーロー × 築地本願寺
- 江州音頭 × 築地本願寺

## 曲レビュー例
- 盆ジョビ
- 郡上おどり
