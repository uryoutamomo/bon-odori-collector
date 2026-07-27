# 日次X収穫サマリ

- 生成時刻: 2026-07-27T10:18:40.405533+00:00
- 対象期間: 直近 3 日
- 対象voices: 1918件
- 候補総数: 158件

## 内訳
- 曲×会場共起: 10件
- 曲候補: 139件
- 用語候補: 9件

## レビュー対象
- 用語・共起レビュー: 19件
- 曲候補レビュー: 2件
- 曲の明白候補 dry-run: 108件
- 曲ノイズ除外: 29件

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
- きよしのズンドコ節 × 晴海ふ頭公園
- ご当地曲の六本人音頭 × 六本木ヒルズアリーナ
- どんどん降ってきても踊り × 浜町公園
- 大東京音頭 × 北柏木公園
- 東京音頭 × 北柏木公園
- 河内音頭 × 築地本願寺
- 納涼音頭 × 築地本願寺
- 輪に入って踊り × 北柏木公園
- 練習会
- 踊り会

## 曲レビュー例
- 盆ジョビ
- 郡上おどり
