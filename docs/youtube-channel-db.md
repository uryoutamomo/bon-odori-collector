# YouTubeチャンネルDB運用メモ

作成: 2026-06-15 / おと（Codex）

## 位置づけ

- YouTube関連作業の入口は Notion「今後の課題リスト: YouTubeデータ活用」。
  - https://app.notion.com/p/YouTube-37f8be04e762814ca63fdff18fe6cf35
- `data/youtube_channel_registry.json` を収集対象チャンネルの台帳にする。
- `data/youtube_channels.json` は既存収集データから作る分析結果で、手編集しない。
- `data/youtube_channel_review.json` は採用判断の証跡として残す。

## 登録ステータス

- `active`: 収集対象。通常はRSS取得や手動収集の対象にする。
- `watch`: 採用候補。証拠品質はあるが、定期収集にはまだ入れない。2026-06-15時点では採用済みチャンネルはactiveへ昇格済み。
- `review`: 自動スコアはあるが人間判断待ち。
- `hold`: 現行範囲外または継続ソースとして弱い。

## 収集ルール

- 通常収集の対象は `status=active` かつ `collection_enabled=true` のみ。
- YouTube単独では新規イベントを本登録しない。
- 既存イベントに一致する場合は、動画URL、チャンネル名、サムネイル、曲目候補を証拠として追記する。
- サムネイルは動画証拠の文脈で使い、会場写真として扱わない。
- `date_validation_required=true` のチャンネルは、動画説明欄の日付を暦・公式情報と照合する。

## 手動実行の扱い

- 採用済みチャンネルは定期ジョブを増やさず、必要時に手動で `collect.py` を実行してRSS由来のYouTube候補を取り込む。
- 検索APIを広げる前に、activeチャンネルRSS、既存YouTube動画、既存イベント照合を優先する。
- 重複はRSS URL、YouTube `video_id`、既存イベント詳細欄の `youtube_evidence` URLで排除する。
- quotaを使う検索拡張は、activeチャンネル由来の未処理候補が尽きた後に検討する。

## 接続先

- チャンネル台帳: `data/youtube_channel_registry.json`
- 動画証拠: `youtube_evidence`
- 曲目証拠: `source=youtube_setlist_occurrence`
- 公開UI: `data/public/events_public.json` の `youtube_evidence`
- 全国展開候補: `data/youtube_nationwide_hold_candidates.json`
- 証拠設計: `docs/youtube-evidence-architecture.md`
