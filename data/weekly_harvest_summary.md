# 日次X収穫サマリ

- 生成時刻: 2026-07-29T09:25:46.304271+00:00
- 対象期間: 直近 3 日
- 対象voices: 3668件
- 候補総数: 203件

## 内訳
- 曲×会場共起: 14件
- 曲候補: 179件
- 用語候補: 10件

## レビュー対象
- 用語・共起レビュー: 24件
- 曲候補レビュー: 1件
- 曲の明白候補 dry-run: 143件
- 曲ノイズ除外: 35件

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
- ご当地音頭 × 浄土寺
- ダンシングヒーロー × 青山善光寺
- きよしのズンドコ節 × 晴海ふ頭公園
- しゃけこも踊り × 築地本願寺
- どんどん降ってきても踊り × 浜町公園
- やぐらを囲む大きな踊り × 築地本願寺
- ガッツリ楽しく踊り × 花園神社
- ダンシングヒーロー × 築地本願寺
- 河内音頭 × 築地本願寺
- 納涼音頭 × 築地本願寺
- 行儀よく踊り × 青山善光寺

## 曲レビュー例
- 盆ジョビ
