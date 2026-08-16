# 日次X収穫サマリ

- 生成時刻: 2026-08-15T07:17:52.450152+00:00
- 対象期間: 直近 3 日
- 対象voices: 3300件
- 候補総数: 220件

## 内訳
- 曲×会場共起: 6件
- 曲候補: 206件
- 用語候補: 8件

## レビュー対象
- 用語・共起レビュー: 14件
- 曲候補レビュー: 7件
- 曲の明白候補 dry-run: 135件
- 曲ノイズ除外: 64件

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
- 中央区音頭 × 浜町公園
- 踊り会
- 練習会
- 参戦
- 踊り始め
- はしご
- ハシゴ

## 曲レビュー例
- たいとう音頭
- 郡上おどり
- 盆ジョビ
- まんまる音頭
- ゆかた音頭
- 東京本願寺音頭
- 神田明神音頭
