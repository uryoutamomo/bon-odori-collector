# 日次X収穫サマリ

- 生成時刻: 2026-08-23T07:16:39.679075+00:00
- 対象期間: 直近 3 日
- 対象voices: 2894件
- 候補総数: 187件

## 内訳
- 曲×会場共起: 20件
- 曲候補: 157件
- 用語候補: 10件

## レビュー対象
- 用語・共起レビュー: 30件
- 曲候補レビュー: 9件
- 曲の明白候補 dry-run: 104件
- 曲ノイズ除外: 44件

## 生成物
- non_song_json: `data/weekly_harvest_review_candidates.json`
- non_song_ui: `data/weekly_harvest_review_ui.html`
- song_json: `data/weekly_song_candidates_review.json`
- song_ui: `data/weekly_song_candidates_review_ui.html`

## 反映コマンド
- `python apply_weekly_song_review_decisions.py --dry-run`
- `python apply_weekly_harvest_human13_decisions.py --candidates data/weekly_harvest_review_candidates.json --decisions data/weekly_harvest_review_decisions.json --out data/weekly_harvest_apply_result.json --dry-run`

## 用語・共起レビュー例
- 南越谷阿波踊り × 六本木ヒルズアリーナ
- たいとう音頭 × 上野恩賜公園
- 南越谷阿波踊り × 大井町駅前中央通り
- 南越谷阿波踊り × 浜町公園
- 六本人音頭 × 六本木ヒルズアリーナ
- ドラえもん音頭 × 六本木ヒルズアリーナ
- 最終日・本踊り × 六本木ヒルズアリーナ
- 最終日・本踊り × 大井町駅前中央通り
- 東京音頭 × 上野恩賜公園
- 舞台踊り × 六本木ヒルズアリーナ
- 舞台踊り × 大井町駅前中央通り
- 舞台踊り × 浜町公園

## 曲レビュー例
- たいとう音頭
- 郡上おどり
- 六本人音頭
- 盆ジョビ
- ズンパ音頭
- 常磐炭坑節
- ふるさと音頭
- スーダラ節
- 東京五輪音頭
