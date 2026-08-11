# 日次X収穫サマリ

- 生成時刻: 2026-08-11T07:58:51.471587+00:00
- 対象期間: 直近 3 日
- 対象voices: 3281件
- 候補総数: 248件

## 内訳
- 曲×会場共起: 9件
- 曲候補: 233件
- 用語候補: 6件

## レビュー対象
- 用語・共起レビュー: 15件
- 曲候補レビュー: 10件
- 曲の明白候補 dry-run: 146件
- 曲ノイズ除外: 77件

## 生成物
- non_song_json: `data/weekly_harvest_review_candidates.json`
- non_song_ui: `data/weekly_harvest_review_ui.html`
- song_json: `data/weekly_song_candidates_review.json`
- song_ui: `data/weekly_song_candidates_review_ui.html`

## 反映コマンド
- `python apply_weekly_song_review_decisions.py --dry-run`
- `python apply_weekly_harvest_human13_decisions.py --candidates data/weekly_harvest_review_candidates.json --decisions data/weekly_harvest_review_decisions.json --out data/weekly_harvest_apply_result.json --dry-run`

## 用語・共起レビュー例
- 東京音頭 × 青山善光寺
- 活気あふれる踊り × 青山善光寺
- 炭坑節 × 青山善光寺
- おこさ節 × 隅田公園
- も連日東京音頭や炭坑節 × 隅田公園
- 大江戸助六音頭 × 築地本願寺
- 江戸川ふるさと音頭 × 鹿骨中学校
- 法輪音頭 × 築地本願寺
- 築地音頭 × 築地本願寺
- 練習会
- 踊り会
- 参戦

## 曲レビュー例
- 郡上おどり
- ゆかた音頭
- 盆ジョビ
- おこさ節
- ひろしのさくら音頭
- らんまん踊り
- ズンパ音頭
- 濱町音頭
- 神田明神音頭
- 築地音頭
