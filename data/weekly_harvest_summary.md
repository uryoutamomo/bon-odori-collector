# 日次X収穫サマリ

- 生成時刻: 2026-07-17T08:30:43.220464+00:00
- 対象期間: 直近 3 日
- 対象voices: 760件
- 候補総数: 109件

## 内訳
- 曲×会場共起: 16件
- 曲候補: 88件
- 用語候補: 5件

## レビュー対象
- 用語・共起レビュー: 21件
- 曲候補レビュー: 1件
- 曲の明白候補 dry-run: 70件
- 曲ノイズ除外: 17件

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
- 大東京音頭 × 靖国神社
- 東京音頭 × 靖国神社
- 多くの踊り × 靖国神社
- おしりたんてい音頭 × 晴海ふ頭公園
- みんなで楽しく踊り × 晴海ふ頭公園
- を掛け声かけながら踊り × 靖国神社
- ドンパン節 × 靖国神社
- 全国屈指の河内音頭 × 牛嶋神社
- 千代田踊り × 靖国神社
- 本場・大阪からも踊り × 牛嶋神社
- 河内音頭 × 牛嶋神社

## 曲レビュー例
- 郡上おどり
