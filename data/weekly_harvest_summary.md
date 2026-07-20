# 日次X収穫サマリ

- 生成時刻: 2026-07-20T08:28:39.331442+00:00
- 対象期間: 直近 3 日
- 対象voices: 1160件
- 候補総数: 153件

## 内訳
- 曲×会場共起: 15件
- 曲候補: 131件
- 用語候補: 7件

## レビュー対象
- 用語・共起レビュー: 22件
- 曲候補レビュー: 3件
- 曲の明白候補 dry-run: 110件
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
- らんまん踊り × 靖国神社
- 多くの踊り × 靖国神社
- 大東京音頭 × 靖国神社
- 東京音頭 × 靖国神社
- ダンシングヒーロー × 晴海ふ頭公園
- おしりたんてい音頭 × 晴海ふ頭公園
- つるまき音頭 × 鶴巻小学校
- 江戸川おどり × 鶴巻小学校
- 津久戸子ども音頭 × 鶴巻小学校
- 真室川音頭 × 浄土寺
- 赤坂あかね音頭 × 浄土寺
- 赤坂は素敵な踊り × 浄土寺

## 曲レビュー例
- 徳島市阿波おどり
- 盆ジョビ
- 郡上おどり
