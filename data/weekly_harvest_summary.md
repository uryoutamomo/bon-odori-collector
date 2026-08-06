# 日次X収穫サマリ

- 生成時刻: 2026-08-06T09:24:45.395437+00:00
- 対象期間: 直近 3 日
- 対象voices: 3433件
- 候補総数: 232件

## 内訳
- 曲×会場共起: 14件
- 曲候補: 210件
- 用語候補: 8件

## レビュー対象
- 用語・共起レビュー: 22件
- 曲候補レビュー: 9件
- 曲の明白候補 dry-run: 129件
- 曲ノイズ除外: 72件

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
- 9日は浜町音頭 × 西久保八幡神社
- りんご節 × 花園神社
- ホームラン音頭 × 築地本願寺
- 八木節 × 花園神社
- 地元の人が踊り × 原町天祖神社
- 定番曲に世田谷音頭 × 駒沢緑泉公園
- 新宿音頭 × 花園神社
- 是非踊り × 上野恩賜公園
- 東京音頭 × 青山善光寺
- 松の木小唄 × 花園神社
- 活気あふれる踊り × 青山善光寺

## 曲レビュー例
- 盆ジョビ
- たいとう音頭
- らんまん踊り
- りんご節
- 新宿音頭
- 白浜音頭
- 神田明神音頭
- 能登島さし音頭
- 風流踊り
