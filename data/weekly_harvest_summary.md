# 日次X収穫サマリ

- 生成時刻: 2026-08-07T07:59:27.520760+00:00
- 対象期間: 直近 3 日
- 対象voices: 3502件
- 候補総数: 209件

## 内訳
- 曲×会場共起: 15件
- 曲候補: 185件
- 用語候補: 9件

## レビュー対象
- 用語・共起レビュー: 24件
- 曲候補レビュー: 9件
- 曲の明白候補 dry-run: 120件
- 曲ノイズ除外: 56件

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
- ユタゴン音頭 × 上野恩賜公園
- 八木節 × 花園神社
- 新宿音頭 × 花園神社
- 東京音頭 × 青山善光寺
- 活気あふれる踊り × 青山善光寺
- 炭坑節 × 青山善光寺
- みんなでユタゴン音頭 × 上野恩賜公園
- りんご節 × 花園神社
- ズンバ音頭 × 花園神社
- 定番曲に世田谷音頭 × 駒沢緑泉公園
- 是非踊り × 上野恩賜公園

## 曲レビュー例
- 新宿音頭
- 盆ジョビ
- たいとう音頭
- らんまん踊り
- りんご節
- 白浜音頭
- 神田明神音頭
- 能登島さし音頭
- 郡上おどり
