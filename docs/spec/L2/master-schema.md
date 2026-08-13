---
id: L2-master-schema
layer: L2
title: マスタRDBスキーマ契約
owns:
  - master_rdb/master_db.py
depends_on:
  - L1-master
invariants:
  - INV-SCH-001
  - INV-SCH-002
  - INV-SCH-003
verified_by:
  - tests/test_master_db_connection_guards.py
updated_for: 6537e7f
---

# マスタRDBスキーマ契約

> 責務と運用は[マスタL1](../L1/04-master.md)。ここではSQLiteのテーブル、キー、観測と確定の境界を定義する。

## 何を表すか

RDBは「同名の行事」ではなく、繰り返される**イベント系列**と、その年ごとの**開催回**を分けて保持する。さらに外部から得た観測を、確定レコードと混同しないまま保存する。`master_rdb/master_db.py` の `SCHEMA` が正本であり、アプリ側のJSONはこの契約を置き換えない。

## 中心エンティティと関係

```text
venues ──< event_series ──< event_occurrences ──< occurrence_dates
                    │                 ├──< occurrence_songs ──< occurrence_song_evidence_links >── evidence_items
                    │                 └──< occurrence_evidence_links ─────────────────────────────> evidence_items
                    └──< event_series_aliases

observed_occurrences ──< observed_occurrence_songs
       └─ matched_occurrence_id ──> event_occurrences
```

| テーブル | 役割 | `6537e7f`時点の行数 |
| --- | --- | ---: |
| `event_series` / `event_occurrences` | 年をまたぐ系列 / 年ごとの開催回 | 347 / 364 |
| `venues` / `venue_aliases` | 会場の正規名 / 同定用別名 | 342 / 402 |
| `songs` / `occurrence_songs` | 曲の正規名 / 開催回での確定・予測曲 | 399 / 819 |
| `evidence_items` | URL・本文・時刻等を持つ原根拠 | 31,329 |
| `observed_occurrences` / `observed_occurrence_songs` | 外部入力の観測（未確定可） | 2,164 / 30,883 |
| `occurrence_dates` / `predicted_occurrence_dates` | 根拠付き日付 / 推測日付 | 417 / 14 |
| `review_inbox_items` | 人へ渡す判断待ち項目 | 576 |

観測曲が30,883件で確定側が819件なのは意図した差である。観測は原文から広く集め、同定・根拠確認を経たものだけを `occurrence_songs` に置く。

## 年次と同定

`event_series.series_key` は年を含まない系列の一意キーで、表示名も年を原則含めない。`event_occurrences` は `series_id`、`event_year`、`occurrence_sequence` の一意組で年ごとの開催回を表す。複数回開催にも `occurrence_sequence` で対応する。会場は系列の通常会場と開催回の実会場を別々に持つ。

`inherited_from_occurrence_id` は過去年との由来を記録する外部キーで、過去年情報を今年の確定情報へコピーする印ではない。`event_series_aliases`（25行）は別名を少数の明示的な同定規則として持つ表であり、名称の曖昧な自動併合をする表ではない。

## 確定・推測・観測の境界

`occurrence_dates` は特定の `occurrence_id` に結び、日付・根拠種別・確信度・根拠IDを持つ。対して `predicted_occurrence_dates` は `historical_promotion_candidates` を起点に、予測年、根拠方式、スコア、適用状態を保持する候補である。予測の `target_occurrence_id` は任意で、系列だけに結び付く候補を許す。

開催回の `current_event_state` と `date_certainty_tier` も別軸である。前者は predicted/announced/confirmed/ended/cancelled、後者は confirmed/rule_predicted/historical_slide/season_hint/historical_reference を表す。したがって過去年の根拠は将来開催の確定日へ昇格しない。これはL1-masterの「今年の確定には今年の根拠」のデータ上の受け皿である。

## 根拠の参照方法

`evidence_items` はプラットフォーム、種別、URL、公開・観測時刻、原文抜粋、原payloadを一度保存する。根拠は開催回へ `occurrence_evidence_links`（対象とリンク状態・信頼度付き）、曲へ `occurrence_song_evidence_links` を通して多対多で結ぶ。同じ根拠を複数の開催回・曲へ引用でき、根拠本文をコピーしない。

未同定の外部入力は `observed_occurrences` と `observed_occurrence_songs` に残し、`matched_*` と `match_status` で確定側への対応の有無を明示する。観測を消して確定表へ直接入れると、後で同定規則を直せず、根拠の出所も失われる。

## スキーマ不変条件

### INV-SCH-001 系列内の開催回は年・回数で一意である

- **内容**: `event_occurrences` は `UNIQUE(series_id, event_year, occurrence_sequence)` を持つ。
- **なぜ**: 同じ年次開催回が二重に作られると日付・曲・根拠が別々の行へ分裂するから。
- **破れたときの症状**: 同じ行事が公開・レビューで二重に見え、片方だけ更新される。
- **守っているコード**: `master_rdb/master_db.py` の `event_occurrences` 定義
- **守っているテスト**: **なし（要追加）**

### INV-SCH-002 確定・終了の開催回は confirmed の日付確実性だけを持つ

- **内容**: insert/update trigger は `confirmed` / `ended` と非`confirmed`の `date_certainty_tier` の組合せを拒否し、予測・告知状態に `confirmed` を付けることも拒否する。
- **なぜ**: 状態と日付の確からしさを一つの曖昧な列にすると、過去年や規則予測を今年の確定として公開するから。
- **破れたときの症状**: 未確認の日程が確定表示される、または確定済み開催の状態が下流で解釈できない。
- **守っているコード**: `master_rdb/master_db.py` の `validate_event_state_axes_insert` / `validate_event_state_axes_update`
- **守っているテスト**: **なし（要追加）**

### INV-SCH-003 スキーマ変更は適用済みmigrationとして記録する

- **内容**: `schema_migrations.version` は主キーで、初期化・migration適用は版と名称、適用時刻を保存する。接続時は `PRAGMA foreign_keys = ON` を設定する。
- **なぜ**: DBファイルだけを差し替えて構造を退行させると、下流が期待する列・外部キーを失い、原因が追えないから。
- **破れたときの症状**: 昨日まで通った処理が列不足や孤立参照で失敗し、どのDB世代か分からない。
- **守っているコード**: `master_rdb/master_db.py` の `schema_migrations`、`apply_migration()`、`connect_existing()`
- **守っているテスト**: **なし（要追加）**

## 変更時の確認

テーブル追加・列名変更はmigration、RDB artifactのスキーマ版、readerを同時に確認する。外部根拠を確定表へ直接コピーせず、まず観測または `evidence_items` とリンクを作る。年次修正では `series_key` を変える前に、対象が系列の名称修正か特定年の開催回修正かを分ける。

---

おと（Codex）
