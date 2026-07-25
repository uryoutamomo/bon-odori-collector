# 日次X収穫サマリ

- 生成時刻: 2026-07-25T15:21:19.546608+00:00
- 対象期間: 直近 3 日
- 対象voices: 414件
- 候補総数: 70件

## 内訳
- 曲×会場共起: 5件
- 曲候補: 58件
- 用語候補: 7件

## レビュー対象
- 用語・共起レビュー: 12件
- 曲候補レビュー: 2件
- 曲の明白候補 dry-run: 45件
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
- おしりたんてい音頭 × 晴海ふ頭公園
- こいち祭はご当地新橋音頭 × 浄土寺
- 大東京音頭 × 北柏木公園
- 新橋音頭 × 桜田公園
- 東京音頭 × 北柏木公園
- 練習会
- ハシゴ
- 踊り会
- 参戦
- 踊り始め
- 梯子
- 盆活

## 曲レビュー例
- 盆ジョビ
- 郡上おどり
