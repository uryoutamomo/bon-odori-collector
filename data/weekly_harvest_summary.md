# 日次X収穫サマリ

- 生成時刻: 2026-08-10T08:08:57.108996+00:00
- 対象期間: 直近 3 日
- 対象voices: 2034件
- 候補総数: 153件

## 内訳
- 曲×会場共起: 11件
- 曲候補: 136件
- 用語候補: 6件

## レビュー対象
- 用語・共起レビュー: 17件
- 曲候補レビュー: 4件
- 曲の明白候補 dry-run: 85件
- 曲ノイズ除外: 47件

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
- クックロビン音頭 × 神田明神境内
- 大江戸助六音頭 × 築地本願寺
- 河内音頭 × 築地本願寺
- 法輪音頭 × 築地本願寺
- 盆ジョビ × 築地本願寺
- 神田明神音頭 × 神田明神境内
- 築地音頭 × 築地本願寺
- 錦糸町高架下河内音頭 × 築地本願寺
- 練習会

## 曲レビュー例
- 盆ジョビ
- らんまん踊り
- 神田明神音頭
- 築地音頭
