# 日次X収穫サマリ

- 生成時刻: 2026-07-18T08:11:09.715916+00:00
- 対象期間: 直近 3 日
- 対象voices: 814件
- 候補総数: 112件

## 内訳
- 曲×会場共起: 12件
- 曲候補: 94件
- 用語候補: 6件

## レビュー対象
- 用語・共起レビュー: 18件
- 曲候補レビュー: 2件
- 曲の明白候補 dry-run: 79件
- 曲ノイズ除外: 13件

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
- ドンパン節 × 靖国神社
- 全国屈指の河内音頭 × 牛嶋神社
- 千代田踊り × 靖国神社
- 本場・大阪からも踊り × 牛嶋神社
- 河内音頭 × 牛嶋神社
- 炭坑節 × 靖国神社
- 阿波踊り × 靖国神社

## 曲レビュー例
- 盆ジョビ
- 郡上おどり
