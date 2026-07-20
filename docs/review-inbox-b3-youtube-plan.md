# Review inbox B3: YouTube 移行計画

## 対象と順序

B3は既存のYouTube収集、API quota制御、automation branchを維持したまま、人間判断待ちの出口だけを統合受信箱へ移す。

1. `youtube_active_video_review.json`
2. `youtube_year_backfill_review_queue.json`
3. `youtube_user_confirmation_queue.json`

2026-07-20時点のlegacy inventoryはactive video 4,414件中pending 86件、year backfill 20件中pending 0件、user confirmation 4件中pending 0件。最初のPRはactive videoの純粋adapter、有限decision route、fixture parityだけを追加し、RDB・workflow・reader・公開データは変更しない。

## identity契約

- 3つのadapterは共通の `source_id=youtube_evidence` を使う。
- `source_key` は `video:<video_id>|occurrence:<occurrence_id>`、開催回が未同定なら `video:<video_id>|year:<year>` とする。
- title、channel名、説明、同一年内の日付訂正、YouTube URL表記はidentityに含めない。
- 同じvideo/targetを複数JSONまたはURL表記違いから投入した場合はduplicate stable IDとしてfail closedする。
- target occurrenceまたはyearが変わる場合は別の意味対象として別IDにする。

## active video境界

legacy consoleと同じく次だけをpendingにする。

- `needs_official_confirmation`
- `review_video_evidence`
- `bon_component_of_parent_event` のうち既知曲証拠で自動解決されていないもの

既知曲判定はadapterへ語彙を注入し、adapter本体は副作用なしに保つ。snapshotにはprimary JSONのSHA-256に加えて、使用した曲語彙ファイルのSHA-256とsizeを記録する。現行実データでは86件（`add_song_evidence` 84件、`needs_research` 2件）となる。

## decision境界

YouTube inboxの選択肢は次の4つだけに固定する。

- `add_song_evidence`: `youtube_song_evidence` domain packetをstageする
- `needs_research`: research follow-upへstageする
- `reject`: applyなしで終了する
- `hold`: applyなしで保留する

acceptでもMaster RDBや公開JSONへ直接書かない。video IDまたはsource URL欠落、未知のaccept action、source ID不一致はpacketを作らず停止する。

## rolloutと閉鎖条件

adapter merge後、別PRでdefault-off dual-writeを配線する。実スケジュールrun 2回についてlegacy pendingとinboxのstable key集合、event/year/source URL/recommended action/payload hashを照合し、差分0を確認する。決定往復、staging、重複なし、workflow green、rollback、独立レビューを確認するまでlegacy writer/readerは維持する。

おと（Codex）
