# 週次収穫サマリ

- 生成時刻: 2026-06-18T12:42:34.494872+00:00
- 対象期間: 直近 7 日
- 対象voices: 993件
- 候補総数: 99件

## 内訳
- 曲×会場共起: 12件
- 曲候補: 78件
- 用語候補: 9件

## レビュー対象
- 用語・共起レビュー: 21件
- 曲候補レビュー: 2件
- 曲の明白候補 dry-run: 65件
- 曲ノイズ除外: 11件

## 生成物
- non_song_json: `data/weekly_harvest_review_candidates.json`
- non_song_ui: `data/weekly_harvest_review_ui.html`
- song_json: `data/weekly_song_candidates_review.json`
- song_ui: `data/weekly_song_candidates_review_ui.html`

## 反映コマンド
- `python apply_weekly_song_review_decisions.py --dry-run`
- `python apply_weekly_harvest_human13_decisions.py --candidates data/weekly_harvest_review_candidates.json --decisions data/weekly_harvest_review_decisions.json --out data/weekly_harvest_apply_result.json --dry-run`

## 用語・共起レビュー例
- 山王音頭 × 山王パークタワー公開空地
- 東京音頭 × 飛鳥山公園
- 飛鳥山公園輪踊り × 飛鳥山公園
- らんまん踊り × 山王パークタワー公開空地
- 水戸黄門おどり × 山王パークタワー公開空地
- おこさ節 × 山王パークタワー公開空地
- ぜひみなさん一緒に踊り × 山王パークタワー公開空地
- 千代田おどり × 山王パークタワー公開空地
- 千代田踊り × 山王パークタワー公開空地
- 沢山踊り × 大正大学
- 相馬甚句 × 山王パークタワー公開空地
- 花笠踊り × 山王パークタワー公開空地

## 曲レビュー例
- 郡上おどり
- 飛鳥山公園輪踊り
