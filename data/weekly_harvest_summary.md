# 日次X収穫サマリ

- 生成時刻: 2026-07-21T08:47:21.458291+00:00
- 対象期間: 直近 3 日
- 対象voices: 1205件
- 候補総数: 149件

## 内訳
- 曲×会場共起: 13件
- 曲候補: 129件
- 用語候補: 7件

## レビュー対象
- 用語・共起レビュー: 20件
- 曲候補レビュー: 2件
- 曲の明白候補 dry-run: 108件
- 曲ノイズ除外: 19件

## 生成物
- non_song_json: `data/weekly_harvest_review_candidates.json`
- non_song_ui: `data/weekly_harvest_review_ui.html`
- song_json: `data/weekly_song_candidates_review.json`
- song_ui: `data/weekly_song_candidates_review_ui.html`

## 反映コマンド
- `python apply_weekly_song_review_decisions.py --dry-run`
- `python apply_weekly_harvest_human13_decisions.py --candidates data/weekly_harvest_review_candidates.json --decisions data/weekly_harvest_review_decisions.json --out data/weekly_harvest_apply_result.json --dry-run`

## 用語・共起レビュー例
- ダンシングヒーロー × 晴海ふ頭公園
- おしりたんてい音頭 × 晴海ふ頭公園
- 真室川音頭 × 浄土寺
- 赤坂小唄 × 浄土寺
- つるまき音頭 × 鶴巻小学校
- の出演や万博音頭 × 大正大学
- 根津藍染通り音頭 × 赤坂氷川神社
- 江戸川おどり × 鶴巻小学校
- 津久戸子ども音頭 × 鶴巻小学校
- 赤坂あかね音頭 × 浄土寺
- 赤坂は素敵な踊り × 浄土寺
- 赤坂豊川音頭 × 浄土寺

## 曲レビュー例
- 郡上おどり
- 徳島市阿波おどり
