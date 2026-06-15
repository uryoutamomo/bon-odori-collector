# YouTube証拠の公開UI表示メモ

作成: 2026-06-15 / おと（Codex）

## データ

- `data/public/events_public.json`: 正本。
- `data/public/events_public.js`: Claude Design などへ貼り付ける `const EVENTS = [...]` 形式。
- 各イベントの `youtube_evidence` は配列。主なフィールド:
  - `video_url`
  - `channel`
  - `thumbnail_url`
  - `songs`
  - `event_name`
  - `detected_date`

## 表示方針

- イベント詳細内に「動画で見る」または「YouTube実績」セクションを置く。
- `video_url` は必ず出典リンクとして表示する。
- `thumbnail_url` はカード詳細やモーダル内で任意表示。一覧カードには出しすぎない。
- `songs` は既存の曲目ヒントの補強として表示し、公式曲目とは区別する。
- 表示ラベルは「2025実績証拠」など `label` を使い、動画由来であることを明示する。

## 注意

- `detail` 本文にも `[youtube_evidence]` ブロックは残っている。既存UI互換のため削らない。
- 新規イベント作成の根拠にはしない。YouTube証拠は過去実績・曲目の補助情報として扱う。
