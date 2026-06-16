# YouTube証拠データ設計メモ

作成: 2026-06-16 / おと（Codex）

## 結論

短期は既存どおり、イベント詳細欄へ `[youtube_evidence]` ブロックとして追記する。公開データでは `data/public/events_public.json` の `youtube_evidence` 配列に構造化して出す。

中期は、イベント本体とは別に「YouTube証拠」または「発生実績 occurrence」相当のDBへ分離する。イベント本DBには、公式開催情報と公開表示に必要な要約だけを残す。

## 理由

- YouTubeは過去実績・曲目・現地状況の強い証拠だが、公式開催情報ではない。
- 動画単独で新規イベントを作ると、日付や会場の誤認が本DBへ入る。
- 1イベントに複数動画が紐づくため、詳細欄だけでは重複排除や曲目集約が難しくなる。
- サムネイルは動画証拠であり、会場写真として扱うべきではない。

## 短期運用

- 既存イベント一致: `apply_*youtube*` 系スクリプトで詳細欄へ `[youtube_evidence]` を追記する。
- 新規イベント候補: 公式ページ、公式SNS、主催者情報、または複数信頼ソースで日付・会場・名称を確認するまで本登録しない。
- 公開UI: `youtube_evidence.video_url` は出典リンクとして必ず表示し、`thumbnail_url` は詳細内で任意表示にする。
- 曲目: `songs` は動画由来の補助情報として扱い、公式曲目とは区別する。

## 中期DB候補

YouTube証拠DBの最小フィールド:

- `event_relation`: 対象イベント。未確定の場合は空。
- `event_name_hint`: 動画から読めるイベント名。
- `venue_hint`: 動画から読める会場名。
- `detected_event_date`: 動画タイトル/説明欄から抽出した日付。
- `video_url`
- `video_id`
- `channel`
- `thumbnail_url`
- `songs`
- `source_status`: `matched_existing_event`、`needs_official_confirmation`、`review_video_evidence`、`out_of_scope`、`ignore`。
- `scope_status`: `tokyo_public_scope`、`hold_for_nationwide_expansion` など。
- `official_confirmation_url`: 公式確認できたURL。未確認なら空。
- `notes`: 曜日矛盾や本文取得不可などの注意。

## RDBスナップショット

`build_youtube_rdb.py` で、既存JSONからローカルSQLite `data/youtube_evidence.sqlite` を生成する。
これは本番DB移行ではなく、YouTube証拠をリレーショナルに扱うための検証用スナップショット。

主なテーブル:

- `channels`: 採用/保留を含むYouTubeチャンネル台帳。
- `videos`: `voices.json` 由来のYouTube動画。activeレビュー結果があれば `action` や `detected_event_date` を付与する。
- `video_official_urls`: 動画説明欄から見つかったYouTube以外の公式/参考URL。
- `video_event_matches`: 既存公開イベントに一致した動画証拠。
- `setlist_occurrences`: イベント実績単位の曲目 occurrence。
- `occurrence_videos`: occurrence と元動画の多対多接続。
- `setlist_songs`: occurrence 内の曲目候補。

この形にしておくと、詳細欄の `[youtube_evidence]` 文字列に依存せず、
「あるイベントに紐づく動画一覧」「動画から見つかった公式URL」「曲目候補の集約」をSQLで確認できる。

## X/YouTube共通スナップショット

`build_evidence_rdb.py` で、X と YouTube の投稿証拠を同じ SQLite `data/evidence.sqlite` にまとめる。
こちらは横断検索・アカウント評価・候補レビュー用の作業台。

主なテーブル:

- `source_accounts`: Xアカウント / YouTubeチャンネルを共通の情報源として保持。
- `source_posts`: `voices.json` 由来の X投稿 / YouTube動画を共通化。
- `post_urls`: 投稿本文・media URL・元URLに含まれる外部リンク。
- `x_account_scores`: Xアカウントの価値スコア、ランク、役割タグ。
- `x_candidate_accounts`: social graph由来の候補アカウント。
- `x_candidate_post_reviews`: 候補アカウントの投稿レビュー結果。
- `x_candidate_review_sample_posts`: 昇格判断に使った代表投稿。

短期は `data/evidence.sqlite` を機械処理・分析用、Notionを人間レビューUIとして併用する。
本番の正本DBへ移す場合も、このスキーマをそのまま土台にするのではなく、運用で必要な問い合わせから逆算して整理する。

## 現在の成果物

- `data/youtube_active_video_review.json`: activeチャンネル動画の分類元データ。
- `data/youtube_active_existing_event_update_apply_result.json`: 既存イベント追記結果。
- `data/youtube_official_confirmation_apply_result.json`: 公式確認対象の処理結果。
- `data/youtube_review_video_evidence_apply_result.json`: 短尺動画など動画証拠の処理結果。
- `data/youtube_nationwide_hold_candidates.json`: 現行範囲外の全国展開候補。
- `data/public/events_public.json`: 公開UI向けの `youtube_evidence` 構造化出力。

## 保留ルール

- 渋谷盆踊り2025は、公式URL候補がHTTP 200を返すが本文/REST本文が取得できないため、本登録しない。未公式実績候補として別保持する。
- 横浜開港祭 BON ODORIは、東京23区公開DBの範囲外のため `hold_for_nationwide_expansion` として保持する。
- 渋谷・鹿児島おはら祭は、盆踊り本DBには入れず、周辺の踊り/祭りイベントとして別扱いで保留する。
- Pokémon GO Fest TOKYO 2026 ピカチュウ音頭は、開催情報DBには入れず、曲目・現象メモだけ保持する。
