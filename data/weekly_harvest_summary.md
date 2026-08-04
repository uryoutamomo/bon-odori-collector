# 日次X収穫サマリ

- 生成時刻: 2026-08-04T09:25:03.800958+00:00
- 対象期間: 直近 3 日
- 対象voices: 3660件
- 候補総数: 282件

## 内訳
- 曲×会場共起: 24件
- 曲候補: 249件
- 用語候補: 9件

## レビュー対象
- 用語・共起レビュー: 33件
- 曲候補レビュー: 6件
- 曲の明白候補 dry-run: 125件
- 曲ノイズ除外: 118件

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
- おしりたんてい音頭 × 晴海ふ頭公園
- 八木節 × 花園神社
- 斎太郎節 × 築地本願寺
- 炭坑節 × 築地本願寺
- 炭坑節 × 花園神社
- 英語の炭坑節 × 花園神社
- 9日は浜町音頭 × 西久保八幡神社
- あやめ踊り × 築地本願寺
- アンコールは築地音頭 × 築地本願寺
- ドンパン節 × 花園神社
- フィナーレの築地音頭 × 築地本願寺

## 曲レビュー例
- 盆ジョビ
- BON踊り
- 郡上おどり
- ドン踊り
- 防災神神音頭
- 風流踊り
