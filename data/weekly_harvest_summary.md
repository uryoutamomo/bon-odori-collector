# 日次X収穫サマリ

- 生成時刻: 2026-08-22T07:17:34.069045+00:00
- 対象期間: 直近 3 日
- 対象voices: 2523件
- 候補総数: 174件

## 内訳
- 曲×会場共起: 19件
- 曲候補: 145件
- 用語候補: 10件

## レビュー対象
- 用語・共起レビュー: 29件
- 曲候補レビュー: 10件
- 曲の明白候補 dry-run: 92件
- 曲ノイズ除外: 43件

## 生成物
- non_song_json: `data/weekly_harvest_review_candidates.json`
- non_song_ui: `data/weekly_harvest_review_ui.html`
- song_json: `data/weekly_song_candidates_review.json`
- song_ui: `data/weekly_song_candidates_review_ui.html`

## 反映コマンド
- `python apply_weekly_song_review_decisions.py --dry-run`
- `python apply_weekly_harvest_human13_decisions.py --candidates data/weekly_harvest_review_candidates.json --decisions data/weekly_harvest_review_decisions.json --out data/weekly_harvest_apply_result.json --dry-run`

## 用語・共起レビュー例
- たいとう音頭 × 上野恩賜公園
- 南越谷阿波踊り × 六本木ヒルズアリーナ
- 南越谷阿波踊り × 浜町公園
- 東京音頭 × 上野恩賜公園
- 六本人音頭 × 六本木ヒルズアリーナ
- 南越谷阿波踊り × 大井町駅前中央通り
- 東京音頭 × 青山善光寺
- 活気あふれる踊り × 青山善光寺
- 炭坑節 × 青山善光寺
- 舞台踊り × 六本木ヒルズアリーナ
- 舞台踊り × 大井町駅前中央通り
- 舞台踊り × 浜町公園

## 曲レビュー例
- たいとう音頭
- 郡上おどり
- 盆ジョビ
- 六本人音頭
- ズンパ音頭
- ふるさと音頭
- スーダラ節
- 常磐炭坑節
- 相馬盆唄
- 親鸞おどり
