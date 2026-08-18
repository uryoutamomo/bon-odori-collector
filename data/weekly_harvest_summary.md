# 日次X収穫サマリ

- 生成時刻: 2026-08-18T23:17:47.530388+00:00
- 対象期間: 直近 3 日
- 対象voices: 1686件
- 候補総数: 160件

## 内訳
- 曲×会場共起: 8件
- 曲候補: 142件
- 用語候補: 10件

## レビュー対象
- 用語・共起レビュー: 18件
- 曲候補レビュー: 5件
- 曲の明白候補 dry-run: 92件
- 曲ノイズ除外: 45件

## 生成物
- non_song_json: `data/weekly_harvest_review_candidates.json`
- non_song_ui: `data/weekly_harvest_review_ui.html`
- song_json: `data/weekly_song_candidates_review.json`
- song_ui: `data/weekly_song_candidates_review_ui.html`

## 反映コマンド
- `python apply_weekly_song_review_decisions.py --dry-run`
- `python apply_weekly_harvest_human13_decisions.py --candidates data/weekly_harvest_review_candidates.json --decisions data/weekly_harvest_review_decisions.json --out data/weekly_harvest_apply_result.json --dry-run`

## 用語・共起レビュー例
- たいとう音頭 × 上野恩賜公園
- 東京音頭 × 上野恩賜公園
- 東京音頭 × 青山善光寺
- 活気あふれる踊り × 青山善光寺
- 炭坑節 × 青山善光寺
- Bon踊り × 久富稲荷神社
- 根津音頭 × 根津神社
- 花笠音頭 × 根津神社
- 練習会
- 踊り会
- 参戦
- ハシゴ

## 曲レビュー例
- たいとう音頭
- 郡上おどり
- 盆ジョビ
- BON踊り
- 風流踊り
