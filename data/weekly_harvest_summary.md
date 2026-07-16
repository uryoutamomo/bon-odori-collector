# 日次X収穫サマリ

- 生成時刻: 2026-07-16T08:19:01.642223+00:00
- 対象期間: 直近 3 日
- 対象voices: 802件
- 候補総数: 118件

## 内訳
- 曲×会場共起: 22件
- 曲候補: 90件
- 用語候補: 6件

## レビュー対象
- 用語・共起レビュー: 28件
- 曲候補レビュー: 2件
- 曲の明白候補 dry-run: 71件
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
- ダンシングヒーロー × 靖国神社
- その羽田節 × 羽田神社
- みんなで楽しく踊り × 晴海ふ頭公園
- を掛け声かけながら踊り × 靖国神社
- スッキリ音頭 × 羽田神社
- ダンシングヒーロー × 晴海ふ頭公園
- ダンシングヒーロー × 羽田神社

## 曲レビュー例
- 盆ジョビ
- 郡上おどり
