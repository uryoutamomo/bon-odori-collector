# 週次収穫サマリ

- 生成時刻: 2026-06-25T11:30:01.997981+00:00
- 対象期間: 直近 7 日
- 対象voices: 1456件
- 候補総数: 135件

## 内訳
- 曲×会場共起: 1件
- 曲候補: 127件
- 用語候補: 7件

## レビュー対象
- 用語・共起レビュー: 8件
- 曲候補レビュー: 2件
- 曲の明白候補 dry-run: 105件
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
- 郡上おどり × 新宿住友ビル三角広場
- 練習会
- 踊り会
- 参戦
- はしご
- ハシゴ
- 盆活
- 踊り始め

## 曲レビュー例
- 郡上おどり
- 盆ジョビ
