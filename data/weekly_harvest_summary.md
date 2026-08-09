# 日次X収穫サマリ

- 生成時刻: 2026-08-09T07:25:14.171959+00:00
- 対象期間: 直近 3 日
- 対象voices: 3518件
- 候補総数: 219件

## 内訳
- 曲×会場共起: 18件
- 曲候補: 194件
- 用語候補: 7件

## レビュー対象
- 用語・共起レビュー: 25件
- 曲候補レビュー: 7件
- 曲の明白候補 dry-run: 121件
- 曲ノイズ除外: 66件

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
- おしりたんてい音頭 × 晴海ふ頭公園
- ユタゴン音頭 × 上野恩賜公園
- みんなでユタゴン音頭 × 上野恩賜公園
- クックロビン音頭 × 神田明神境内
- ズンバ音頭 × 花園神社
- 八木節 × 花園神社
- 大江戸助六音頭 × 築地本願寺
- 新宿音頭 × 花園神社
- 河内音頭 × 築地本願寺

## 曲レビュー例
- 盆ジョビ
- らんまん踊り
- たいとう音頭
- 新宿音頭
- 神田明神音頭
- 築地音頭
- 郡上おどり
