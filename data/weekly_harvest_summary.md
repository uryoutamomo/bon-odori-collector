# 日次X収穫サマリ

- 生成時刻: 2026-08-02T08:54:52.139097+00:00
- 対象期間: 直近 3 日
- 対象voices: 3896件
- 候補総数: 272件

## 内訳
- 曲×会場共起: 30件
- 曲候補: 232件
- 用語候補: 10件

## レビュー対象
- 用語・共起レビュー: 40件
- 曲候補レビュー: 1件
- 曲の明白候補 dry-run: 183件
- 曲ノイズ除外: 48件

## 生成物
- non_song_json: `data/weekly_harvest_review_candidates.json`
- non_song_ui: `data/weekly_harvest_review_ui.html`
- song_json: `data/weekly_song_candidates_review.json`
- song_ui: `data/weekly_song_candidates_review_ui.html`

## 反映コマンド
- `python apply_weekly_song_review_decisions.py --dry-run`
- `python apply_weekly_harvest_human13_decisions.py --candidates data/weekly_harvest_review_candidates.json --decisions data/weekly_harvest_review_decisions.json --out data/weekly_harvest_apply_result.json --dry-run`

## 用語・共起レビュー例
- ホームラン音頭 × 築地本願寺
- 大江戸助六音頭 × 築地本願寺
- 斎太郎節 × 築地本願寺
- 法輪音頭 × 築地本願寺
- おしりたんてい音頭 × 晴海ふ頭公園
- 河内音頭 × 築地本願寺
- 炭坑節 × 築地本願寺
- あやめ踊り × 築地本願寺
- あやめ音頭 × 築地本願寺
- それでも冷めない踊り × 築地本願寺
- という程お腹一杯踊り × 築地本願寺
- とは言え踊り × 築地本願寺

## 曲レビュー例
- 盆ジョビ
