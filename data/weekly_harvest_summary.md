# 日次X収穫サマリ

- 生成時刻: 2026-08-24T07:35:17.879332+00:00
- 対象期間: 直近 3 日
- 対象voices: 2882件
- 候補総数: 204件

## 内訳
- 曲×会場共起: 16件
- 曲候補: 178件
- 用語候補: 10件

## レビュー対象
- 用語・共起レビュー: 26件
- 曲候補レビュー: 13件
- 曲の明白候補 dry-run: 119件
- 曲ノイズ除外: 46件

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
- 六本人音頭 × 六本木ヒルズアリーナ
- 南越谷阿波踊り × 浜町公園
- 最終日・本踊り × 六本木ヒルズアリーナ
- 最終日・本踊り × 大井町駅前中央通り
- 舞台踊り × 六本木ヒルズアリーナ
- 舞台踊り × 大井町駅前中央通り
- 舞台踊り × 浜町公園
- ドラえもん音頭 × 六本木ヒルズアリーナ
- 割と普通のナントカ音頭 × 築地本願寺
- 大東京音頭 × 浜町公園

## 曲レビュー例
- たいとう音頭
- 郡上おどり
- 盆ジョビ
- 六本人音頭
- スーダラ節
- ズンパ音頭
- 常磐炭坑節
- 東京五輪音頭
- 板橋音頭
- 津軽甚句
- 真室川音頭
- 荒川音頭
