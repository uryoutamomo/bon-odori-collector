# 日次X収穫サマリ

- 生成時刻: 2026-10-02T12:41:54.198170+00:00
- 対象期間: 直近 3 日
- 対象voices: 35件
- 候補総数: 6件

## 内訳
- 曲×会場共起: 1件
- 曲候補: 5件

## レビュー対象
- 用語・共起レビュー: 1件
- 曲候補レビュー: 1件
- 曲の明白候補 dry-run: 3件
- 曲ノイズ除外: 1件

## 生成物
- non_song_json: `data/weekly_harvest_review_candidates.json`
- non_song_ui: `data/weekly_harvest_review_ui.html`
- song_json: `data/weekly_song_candidates_review.json`
- song_ui: `data/weekly_song_candidates_review_ui.html`

## 反映コマンド
- `python apply_weekly_song_review_decisions.py --dry-run`
- `python apply_weekly_harvest_human13_decisions.py --candidates data/weekly_harvest_review_candidates.json --decisions data/weekly_harvest_review_decisions.json --out data/weekly_harvest_apply_result.json --dry-run`

## 用語・共起レビュー例
- ダンシングヒーロー × 宮下公園

## 曲レビュー例
- 水戸黄門おどり
