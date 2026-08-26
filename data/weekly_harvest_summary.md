# 日次X収穫サマリ

- 生成時刻: 2026-08-26T07:19:54.210310+00:00
- 対象期間: 直近 3 日
- 対象voices: 942件
- 候補総数: 91件

## 内訳
- 曲候補: 84件
- 用語候補: 7件

## レビュー対象
- 用語・共起レビュー: 7件
- 曲候補レビュー: 8件
- 曲の明白候補 dry-run: 58件
- 曲ノイズ除外: 18件

## 生成物
- non_song_json: `data/weekly_harvest_review_candidates.json`
- non_song_ui: `data/weekly_harvest_review_ui.html`
- song_json: `data/weekly_song_candidates_review.json`
- song_ui: `data/weekly_song_candidates_review_ui.html`

## 反映コマンド
- `python apply_weekly_song_review_decisions.py --dry-run`
- `python apply_weekly_harvest_human13_decisions.py --candidates data/weekly_harvest_review_candidates.json --decisions data/weekly_harvest_review_decisions.json --out data/weekly_harvest_apply_result.json --dry-run`

## 用語・共起レビュー例
- 踊り会
- 参戦
- 練習会
- ハシゴ
- 梯子
- 盆活
- 踊り始め

## 曲レビュー例
- たいとう音頭
- 板橋音頭
- 津軽甚句
- 盆ジョビ
- 真室川音頭
- 荒川音頭
- 踊れどれドラドラえもん音頭
- 郡上おどり
