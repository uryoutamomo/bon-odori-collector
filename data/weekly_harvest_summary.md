# 日次X収穫サマリ

- 生成時刻: 2026-08-25T07:15:01.216229+00:00
- 対象期間: 直近 3 日
- 対象voices: 1894件
- 候補総数: 145件

## 内訳
- 曲×会場共起: 7件
- 曲候補: 129件
- 用語候補: 9件

## レビュー対象
- 用語・共起レビュー: 16件
- 曲候補レビュー: 11件
- 曲の明白候補 dry-run: 87件
- 曲ノイズ除外: 31件

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
- 南越谷阿波踊り × 大井町駅前中央通り
- 最終日・本踊り × 六本木ヒルズアリーナ
- 最終日・本踊り × 大井町駅前中央通り
- ドラえもん音頭 × 六本木ヒルズアリーナ
- 六本人音頭 × 六本木ヒルズアリーナ
- 東京五輪音頭 × 晴海ふ頭公園
- 踊り会
- 練習会
- 参戦
- 梯子
- 踊り納め

## 曲レビュー例
- たいとう音頭
- 郡上おどり
- 盆ジョビ
- 六本人音頭
- 常磐炭坑節
- 東京五輪音頭
- 板橋音頭
- 津軽甚句
- 真室川音頭
- 荒川音頭
- 踊れどれドラドラえもん音頭
