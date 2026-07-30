# 日次X収穫サマリ

- 生成時刻: 2026-07-30T09:07:09.339560+00:00
- 対象期間: 直近 3 日
- 対象voices: 3834件
- 候補総数: 236件

## 内訳
- 曲×会場共起: 31件
- 曲候補: 196件
- 用語候補: 9件

## レビュー対象
- 用語・共起レビュー: 40件
- 曲候補レビュー: 2件
- 曲の明白候補 dry-run: 156件
- 曲ノイズ除外: 38件

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
- あやめ踊り × 築地本願寺
- おしりたんてい音頭 × 晴海ふ頭公園
- ホームラン音頭 × 築地本願寺
- 東京音頭 × 築地本願寺
- 炭坑節 × 築地本願寺
- ダンシングヒーロー × 築地本願寺
- ダンシングヒーロー × 青山善光寺
- 斎太郎節 × 築地本願寺
- 法輪音頭 × 築地本願寺

## 曲レビュー例
- 盆ジョビ
- 郡上おどり
