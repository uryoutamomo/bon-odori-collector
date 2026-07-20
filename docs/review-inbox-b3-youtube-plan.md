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

曲証拠判定はlegacyと同じく、行の `songs`、`setlist_occurrences[].setlist` にある構造化済み曲名、またはtitleの既知曲一致を使う。title照合用の既知曲語彙はadapterへ注入し、adapter本体は副作用なしに保つ。snapshotにはprimary JSONのSHA-256に加えて、使用した曲語彙ファイルのSHA-256とsizeを記録する。現行実データでは86件（`add_song_evidence` 84件、`needs_research` 2件）となる。

year backfillは既決定groupを出力せず、未判断group内の動画を1動画1itemへ展開する。active videoと同じ `source_id` と `video:<id>|year:<year>` を使うため、同じ動画・対象年が両JSONに現れてもinbox IDは同一になり、二重表示されない。groupの候補actionは有限の `add_song_evidence` / `needs_research` / `hold` へ写像し、未知actionやdecision矛盾はfail closedする。2026-07-20時点の実キューは20groupすべて既決定のため出力0件。

共通 `source_id=youtube_evidence` のparityは3キュー全体の集合で評価する。year backfillやuser confirmationのsnapshotを単独でsource writerへ渡した場合、既存active行はwriter内で `stale_candidates` に分類され、書き込み自体は成功し得る。一方、3キュー全体の外部parityは不一致になる。3adapter完成後に重複IDを解決したaggregate snapshotを作り、scheduled production入口はaggregate以外を明示的に拒否する。

user confirmationも既決定itemを出力せず、未判断かつ動画URL・対象年・有限optionsが揃うitemだけを同じvideo/year identityへ変換する。部分的な決定状態、未知option/recommendation、動画URLや年の欠落はfail closedする。2026-07-20時点の4件は全て既決定で出力0件。動画URLを持たないgroup型itemが将来pendingへ戻る場合は、元動画URLを補完してから移行する。

production入口はactive video・year backfill・user confirmationの3入力lineageを持つschema version 1のcomplete aggregateだけを受理する。重複stable IDはuser confirmation、year backfill、active videoの順で優先し、選択・除外したqueueとpayload hashをsnapshotへ記録する。単独adapter snapshotはproduction runnerへ渡せない。

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
