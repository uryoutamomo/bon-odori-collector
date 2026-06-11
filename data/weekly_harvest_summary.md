# 週次収穫サマリ

- 生成時刻: 2026-06-11T14:33:01.167063+00:00
- 対象期間: 直近 7 日
- 対象voices: 1056件
- 候補総数: 161件

## 内訳
- 曲×会場共起: 6件
- 曲候補: 148件
- 用語候補: 7件

## レビュー対象
- 用語・共起レビュー: 13件
- 曲候補レビュー: 11件
- 曲の明白候補 dry-run: 70件
- 曲ノイズ除外: 67件

## 生成物
- non_song_json: `data/weekly_harvest_review_candidates.json`
- non_song_ui: `data/weekly_harvest_review_ui.html`
- song_json: `data/weekly_song_candidates_review.json`
- song_ui: `data/weekly_song_candidates_review_ui.html`

## 反映コマンド
- `python apply_weekly_song_review_decisions.py --dry-run`
- `python apply_weekly_harvest_human13_decisions.py --candidates data/weekly_harvest_review_candidates.json --decisions data/weekly_harvest_review_decisions.json --out data/weekly_harvest_apply_result.json --dry-run`

## 用語・共起レビュー例
- 東京音頭 × 飛鳥山公園
- 飛鳥山公園輪踊り × 飛鳥山公園
- あさがお踊り × 飛鳥山公園
- 印西音頭 × 鮫洲入江広場公園
- 山王音頭と千代田踊り × 飛鳥山公園
- 隅田公園そよ風ひろばに踊り × 隅田公園
- 練習会
- 輪踊り
- 踊り会
- 踊り始め
- 参戦
- 梯子

## 曲レビュー例
- 飛鳥山公園輪踊り
- 郡上おどり
- 夜の踊り
- 徳島市阿波おどり
- まんず青山の郡上おどり
- よさこい踊り
- 先日の郡上おどり
- 山王音頭と千代田踊り
- 岡崎音頭と五万石おどり
- 盆ジョビ
- 馬鹿おどり
