# 日次X収穫サマリ

- 生成時刻: 2026-08-21T07:24:52.055014+00:00
- 対象期間: 直近 3 日
- 対象voices: 2699件
- 候補総数: 164件

## 内訳
- 曲×会場共起: 13件
- 曲候補: 141件
- 用語候補: 10件

## レビュー対象
- 用語・共起レビュー: 23件
- 曲候補レビュー: 9件
- 曲の明白候補 dry-run: 90件
- 曲ノイズ除外: 42件

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
- 東京音頭 × 上野恩賜公園
- 東京音頭 × 青山善光寺
- 活気あふれる踊り × 青山善光寺
- 炭坑節 × 青山善光寺
- 南越谷阿波踊り × 六本木ヒルズアリーナ
- 南越谷阿波踊り × 浜町公園
- ドラえもん音頭 × 六本木ヒルズアリーナ
- 伊丹音頭や下関漁港節 × 根津神社
- 六本人音頭 × 六本木ヒルズアリーナ
- 大江戸助六音頭 × 築地本願寺
- 生歌音頭 × 浜町公園

## 曲レビュー例
- たいとう音頭
- 盆ジョビ
- 郡上おどり
- ふるさと音頭
- ズンパ音頭
- 六本人音頭
- 常磐炭坑節
- 相馬盆唄
- 親鸞おどり
